"""CLI for the rubric recalibration loop.

The testable core lives in `screen.recalibration` and the run record in
`screen.recalibration_run`; this file owns the live BAML proposer, Jev-backed
evaluation, and the command-line glue.

Run it as a file path or a dotted module — `-m` will not accept a `.py` suffix:

    uv run python scripts/recalibrate_rubric.py --target location
    uv run python -m scripts.recalibrate_rubric --target location
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Literal

import click
import yaml
from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from screen import recalibration as core
from screen import recalibration_run as runstate
from screen.baml_client.sync_client import b as baml
from screen.extract.prompt import rubric_text_for_dimension
from screen.score.loader import load_scoring_config
from screen.verdict.jev_verdict_provider import JevVerdictProvider
from screen.verdict.protocol import JevRuling, NoulJudgment
from screen.verdict.routing import route_verdict

load_dotenv(Path(__file__).parent.parent / ".env")

_RUBRIC_PATH = Path(__file__).parent.parent / "rubric.yaml"
ContextMode = Literal["sampled", "full", "compare"]


class JevEvaluator:
    def __init__(self, provider: Any, config) -> None:
        self._provider = provider
        self._config = config

    def evaluate(self, pairs: list[core.UsablePair], rubric_text: str) -> core.EvaluationResult:
        def _eval_one(pair: core.UsablePair) -> core.LabeledCase:
            fwd = self._provider.get_ruling(rubric_text, pair.digest_a, pair.digest_b, [])
            rev = self._provider.get_ruling(rubric_text, pair.digest_b, pair.digest_a, [])
            pc = (fwd.clear_winner.p_true + rev.clear_winner.p_true) / 2
            pa = (fwd.a_is_better.p_true + (1 - rev.a_is_better.p_true)) / 2
            ruling = JevRuling(
                clear_winner=NoulJudgment(p_true=pc),
                a_is_better=NoulJudgment(p_true=pa),
            )
            decision = route_verdict(
                ruling,
                tie_commit_threshold=self._config.tie_commit_threshold,
                winner_commit_threshold=self._config.winner_commit_threshold,
            )
            return core.LabeledCase(
                pair_id=pair.pair_id,
                digest_a=pair.digest_a,
                digest_b=pair.digest_b,
                expected=pair.expected,
                jev_prediction=decision.verdict.outcome,
                jev_confidence=decision.verdict.confidence,
                sure=decision.auto_commit,
            )

        cases = list(map(_eval_one, pairs))
        return core.EvaluationResult.from_cases(cases)


class AnthropicProposer:
    def __init__(self, context_mode: ContextMode = "sampled", client: Any = baml) -> None:
        self._context_mode = context_mode
        self._client: Any = client

    def propose(
        self,
        *,
        current_rubric_text: str,
        labeled_cases: list[core.LabeledCase],
        prior_rounds: list[core.RoundResult],
    ) -> core.RubricProposal:
        mismatch_cases = [c for c in labeled_cases if c.jev_prediction != c.expected]
        agree_cases = [c for c in labeled_cases if c.jev_prediction == c.expected]
        generated = self._client.ProposeRubricEdit(
            current_rubric_text=current_rubric_text,
            current_cases_text=self._build_cases_text(mismatch_cases, agree_cases),
            history_text=self._build_history_text(prior_rounds),
        )
        return core.RubricProposal(
            theory=generated.theory,
            expected_effect=generated.expected_effect,
            definition=generated.definition,
            fit_anchor_poor=generated.fit_anchor_poor,
            fit_anchor_mixed=generated.fit_anchor_mixed,
            fit_anchor_strong=generated.fit_anchor_strong,
            look_for=generated.look_for,
        )

    def _build_cases_text(
        self, mismatch_cases: list[core.LabeledCase], agree_cases: list[core.LabeledCase]
    ) -> str:
        def _fmt_cases(cases: list[core.LabeledCase], n: int) -> str:
            out: list[str] = []
            for c in cases[:n]:
                out.append(
                    f"pair={c.pair_id} expected={c.expected} jev={c.jev_prediction} "
                    f"sure={c.sure} conf={c.jev_confidence:.2f}\n"
                    f"A: {c.digest_a}\nB: {c.digest_b}"
                )
            return "\n---\n".join(out) if out else "(none)"

        mismatch_limit = len(mismatch_cases) if self._context_mode == "full" else 10
        agree_limit = len(agree_cases) if self._context_mode == "full" else 5
        return (
            f"## Mismatches ({len(mismatch_cases)} cases)\n{_fmt_cases(mismatch_cases, mismatch_limit)}\n\n"
            f"## Agreements ({len(agree_cases)} cases)\n{_fmt_cases(agree_cases, agree_limit)}"
        )

    def _build_history_text(self, prior_rounds: list[core.RoundResult]) -> str:
        if not prior_rounds:
            return "(none)"

        parts: list[str] = []
        for round_result in prior_rounds:
            fixed = self._format_pair_block("Fixed", round_result.fixed_cases)
            broken = self._format_pair_block("Broken", round_result.broken_cases)
            parts.append(
                "\n".join(
                    [
                        f"Round {round_result.round_num}",
                        f"Theory: {round_result.theory}",
                        f"Expected effect: {round_result.expected_effect or '(not stated)'}",
                        f"Train: {round_result.train_buckets}",
                        f"Noise floor delta: {round_result.noise_floor_delta}",
                        f"Candidate delta: {round_result.candidate_delta}",
                        f"Accepted: {round_result.accepted}",
                        "Candidate draft:",
                        round_result.candidate_rubric_text,
                        fixed,
                        broken,
                    ]
                )
            )
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _format_pair_block(label: str, cases: list[core.LabeledCase]) -> str:
        if not cases:
            return f"{label}: (none)"
        lines = [f"{label} ({len(cases)}):"]
        for c in cases:
            lines.append(
                f"- pair={c.pair_id} expected={c.expected} jev={c.jev_prediction} "
                f"sure={c.sure} conf={c.jev_confidence:.2f}\n  A: {c.digest_a}\n  B: {c.digest_b}"
            )
        return "\n".join(lines)


def _open_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the screening DB read-only.

    Read-only deliberately: this loop must never write to the operator's store.
    That also means pending migrations can't be applied here, so a stale DB is
    reported rather than silently surfacing as a KeyError from the row mappers.
    """
    if db_path is None:
        db_root = Path(os.environ.get("SCREEN_DATA_DIR", "data"))
        db_path = db_root / "screen.db"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _require_current_schema(conn, str(db_path.parent))
    return conn


def _require_current_schema(conn: sqlite3.Connection, db_path: str) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(dimension_digests)")}
    if "id" not in columns:
        raise click.ClickException(
            f"{db_path}/screen.db is behind on migrations "
            f"(dimension_digests has no `id` column). Apply them with: "
            f'uv run python -c "from pathlib import Path; '
            f"from screen.store.db import connect; "
            f"connect(Path('{db_path}/screen.db'))\""
        )


@click.command()
@click.option("--target", required=True, help="Rubric dimension slug.")
@click.option("--rounds", type=int, default=3, show_default=True, help="Proposer rounds to run.")
@click.option(
    "--floor",
    type=int,
    default=70,
    show_default=True,
    help="Minimum usable pairs before a target is eligible.",
)
@click.option("--seed", type=int, default=42, show_default=True, help="Split seed.")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path, dir_okay=False, readable=True),
    default=None,
    help="Path to the SQLite DB (defaults to $SCREEN_DATA_DIR/screen.db or data/screen.db).",
)
@click.option(
    "--context-mode",
    type=click.Choice(["sampled", "full", "compare"], case_sensitive=False),
    default="sampled",
    show_default=True,
    help="How much propose-split context to show the proposer.",
)
@click.option(
    "--state-path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to the resumable run state JSON. If omitted, a new timestamped run dir is created.",
)
def recalibrate(
    target: str,
    rounds: int,
    floor: int,
    seed: int,
    db_path: Path | None,
    context_mode: ContextMode,
    state_path: Path | None,
) -> None:
    """Propose rubric edits for TARGET and measure them on held-out pairs.

    Leaves the winning candidate applied to rubric.yaml but never commits it.
    """
    config = load_scoring_config()

    if context_mode == "compare":
        _run_compare_mode(
            target=target, rounds=rounds, floor=floor, seed=seed, db_path=db_path, config=config
        )
        return

    run_dir = state_path.parent if state_path else runstate.default_run_dir(target)
    evaluator = JevEvaluator(JevVerdictProvider(config, TypeSafeClient()), config)

    if (run_dir / "state.json").exists():
        state = runstate.load_state(run_dir / "state.json")
        try:
            runstate.require_baseline_unchanged(state, rubric_text_for_dimension(target))
        except runstate.ResumeRefusedError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(
            f"[recalibrate] resuming {target} from {state.state_path} "
            f"({state.rounds_completed} round(s) done)"
        )
    else:
        state = _start_run(
            target=target,
            floor=floor,
            seed=seed,
            db_path=db_path,
            context_mode=context_mode,
            run_dir=run_dir,
            evaluator=evaluator,
        )

    if rounds > 0:
        click.echo(f"\n  Running {rounds} more round(s) with {context_mode} context…\n")
        core.run_rounds(
            propose_pairs=state.propose_pairs,
            held_pairs=state.held_pairs,
            labeled_cases=state.current_train.cases,
            current_rubric_text=state.current_rubric_text,
            proposer=AnthropicProposer(context_mode=context_mode),
            evaluator=evaluator,
            n_rounds=rounds,
            baseline_train=state.current_train,
            baseline_noise=state.baseline_noise,
            noise_floor_delta=state.noise_floor_delta,
            round_offset=state.rounds_completed,
            on_round=lambda result: runstate.record_round(state, result),
        )

    _print_results(state)
    _maybe_apply_winner(target, state)


def _start_run(
    *,
    target: str,
    floor: int,
    seed: int,
    db_path: Path | None,
    context_mode: ContextMode,
    run_dir: Path,
    evaluator: JevEvaluator,
) -> runstate.RunState:
    """Measure the baseline twice and pin the run's splits, baseline and noise floor."""
    conn = _open_db(db_path)
    pairs, shortfall = core.load_pairs(conn, target=target, floor=floor)
    if shortfall > 0:
        raise click.ClickException(
            f"{target}: only {floor - shortfall} usable pairs "
            f"(floor={floor}, shortfall={shortfall}). No candidate proposed."
        )
    click.echo(f"[recalibrate] {target}: {len(pairs)} usable pairs — eligible.")
    propose_pairs, held_pairs = core.split_pairs(pairs, seed=seed)
    click.echo(f"  propose={len(propose_pairs)}  held-out={len(held_pairs)}")

    rubric_text = rubric_text_for_dimension(target)
    click.echo("\n  Measuring baseline on the propose split…")
    baseline_train = evaluator.evaluate(propose_pairs, rubric_text)
    click.echo(f"  baseline train: {baseline_train.buckets}")
    click.echo(f"  baseline train cm: {baseline_train.confusion}")
    click.echo("  Measuring the same text again for the noise floor…")
    baseline_noise = evaluator.evaluate(propose_pairs, rubric_text)
    click.echo(f"  baseline noise: {baseline_noise.buckets}")

    state = runstate.new_run_state(
        run_dir=run_dir,
        target=target,
        seed=seed,
        floor=floor,
        context_mode=context_mode,
        baseline_rubric_text=rubric_text,
        baseline_train=baseline_train,
        baseline_noise=baseline_noise,
        propose_pairs=propose_pairs,
        held_pairs=held_pairs,
    )
    click.echo(f"  noise floor delta: {state.noise_floor_delta} pair(s)")
    runstate.save_state(state)
    click.echo(f"  run state: {state.state_path}")
    return state


def _run_compare_mode(
    *,
    target: str,
    rounds: int,
    floor: int,
    seed: int,
    db_path: Path | None,
    config,
) -> None:
    conn = _open_db(db_path)
    pairs, shortfall = core.load_pairs(conn, target=target, floor=floor)
    if shortfall > 0:
        raise click.ClickException(
            f"{target}: only {floor - shortfall} usable pairs "
            f"(floor={floor}, shortfall={shortfall}). No candidate proposed."
        )
    click.echo(f"[recalibrate] {target}: {len(pairs)} usable pairs — eligible.")
    propose_pairs, held_pairs = core.split_pairs(pairs, seed=seed)
    click.echo(f"  propose={len(propose_pairs)}  held-out={len(held_pairs)}")
    provider = JevVerdictProvider(config, TypeSafeClient())
    evaluator = JevEvaluator(provider, config)
    rubric_text = rubric_text_for_dimension(target)
    baseline_train = evaluator.evaluate(propose_pairs, rubric_text)
    baseline_held = evaluator.evaluate(held_pairs, rubric_text)
    click.echo("\n  Comparing sampled and full-context runs…")
    click.echo(f"  baseline train: {baseline_train.buckets}")
    click.echo(f"  baseline held-out: {baseline_held.buckets}")
    for mode in ("sampled", "full"):
        proposer = AnthropicProposer(context_mode=mode)
        click.echo(f"\n  [{mode}] Running {rounds} round(s)…\n")
        results = core.run_rounds(
            propose_pairs=propose_pairs,
            held_pairs=held_pairs,
            labeled_cases=baseline_train.cases,
            current_rubric_text=rubric_text,
            proposer=proposer,
            evaluator=evaluator,
            n_rounds=rounds,
            baseline_train=baseline_train,
            baseline_noise=baseline_train,
        )
        for r in results:
            click.echo(f"  [{mode}] Round {r.round_num}: {r.theory}")
            click.echo(f"    expect:   {r.expected_effect}")
            click.echo(f"    train:    {r.train_buckets}")
            click.echo(f"    train cm: {core.ConfusionMatrix.from_cases(r.train_cases or [])}")
            click.echo(f"    held-out: {r.held_out_buckets}")
            click.echo(f"    delta:    {r.candidate_delta} (noise floor {r.noise_floor_delta})")
        winner = core.best_round(results, baseline_train.buckets, rubric_text)
        if winner is None:
            click.echo(f"  [{mode}] No candidate beat the training objective — no edit proposed.")
        else:
            click.echo(f"  [{mode}] best train: {winner.train_buckets}")
            click.echo(f"  [{mode}] best held:  {winner.held_out_buckets}")


def _print_results(state: runstate.RunState) -> None:
    click.echo(
        f"\n[recalibrate] {state.target}: {state.rounds_completed} round(s) recorded in {state.state_path}"
    )
    click.echo(f"  baseline train: {state.baseline_train.buckets}")
    click.echo(f"  baseline noise: {state.baseline_noise.buckets}")
    click.echo(f"  noise floor delta: {state.noise_floor_delta}")
    for r in state.rounds:
        click.echo(f"\n  Round {r.round_num}: {r.theory}")
        click.echo(f"    expect:   {r.expected_effect}")
        click.echo(f"    train:    {r.train_buckets}")
        click.echo(f"    train cm: {core.ConfusionMatrix.from_cases(r.train_cases or [])}")
        click.echo(f"    held-out: {r.held_out_buckets}")
        click.echo(f"    delta:    {r.candidate_delta} (noise floor {r.noise_floor_delta})")
        click.echo(f"    accepted: {r.accepted}")
        click.echo(f"    fixed:    {len(r.fixed_cases)}")
        click.echo(f"    broken:   {len(r.broken_cases)}")
        if r.fixed_cases:
            click.echo("    fixed pairs:")
            for case in r.fixed_cases:
                click.echo(f"      - {case.pair_id}: {case.digest_a} / {case.digest_b}")
        if r.broken_cases:
            click.echo("    broken pairs:")
            for case in r.broken_cases:
                click.echo(f"      - {case.pair_id}: {case.digest_a} / {case.digest_b}")


def _maybe_apply_winner(target: str, state: runstate.RunState) -> None:
    winner = core.best_round(state.rounds, state.baseline_train.buckets, state.baseline_rubric_text)
    if winner is None or not winner.accepted:
        click.echo(
            "\n[recalibrate] No candidate beat the current best on the paired acceptance rule — no edit proposed. "
            "rubric.yaml unchanged."
        )
        return
    diff = apply_candidate(target, winner.candidate_rubric_text)
    click.echo("\n--- rubric.yaml diff ---")
    click.echo(diff or "(no structural change — definition was functionally identical)")
    click.echo("--- end diff ---")
    click.echo("\nrubric.yaml updated (not committed). Review with `git diff rubric.yaml`.")


def apply_candidate(slug: str, candidate_text: str, *, rubric_path: Path | None = None) -> str:
    """Write a winning candidate back into rubric.yaml and return the git diff.

    The candidate is split with `core.parse_rubric_fields` — the same parser used to
    rehydrate partial proposals — so what lands in YAML is exactly what was measured.
    """
    rubric_path = rubric_path or _RUBRIC_PATH
    doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    fields = core.parse_rubric_fields(candidate_text)
    for dim in doc.get("dimensions", []):
        if dim.get("slug") == slug:
            dim["definition"] = fields["definition"]
            dim["fit_anchors"] = {
                label: fields[f"fit_anchor_{label.lower()}"]
                for label in ("Poor", "Mixed", "Strong")
                if f"fit_anchor_{label.lower()}" in fields
            }
            if fields.get("look_for"):
                dim["look_for"] = fields["look_for"]
            break
    new_yaml = yaml.dump(doc, allow_unicode=True, default_flow_style=False, sort_keys=False)
    rubric_path.write_text(new_yaml, encoding="utf-8")
    result = subprocess.run(
        ["git", "diff", "--", rubric_path.name],
        cwd=rubric_path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


if __name__ == "__main__":
    recalibrate()
