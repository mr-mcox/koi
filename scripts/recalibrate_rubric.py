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
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import click
import yaml
from dotenv import load_dotenv
from baml_py import ClientRegistry
from typesafe_sdk import TypeSafeClient

from screen import recalibration as core
from screen import recalibration_run as runstate
from screen.baml_client.sync_client import b as baml
from screen.extract.prompt import resolve_private, unresolved_rubric_text_for_dimension
from screen.score.loader import load_scoring_config
from screen.verdict.jev_verdict_provider import JevVerdictProvider
from screen.verdict.protocol import JevRuling, NoulJudgment
from screen.verdict.routing import route_verdict

load_dotenv(Path(__file__).parent.parent / ".env")

_RUBRIC_PATH = Path(__file__).parent.parent / "rubric.yaml"
SONNET_MODEL = "claude-sonnet-5"
SONNET_CONNECT_TIMEOUT_MS = 10_000
SONNET_IDLE_TIMEOUT_MS = 100_000
SONNET_REQUEST_TIMEOUT_MS = 900_000
SONNET_MAX_TOKENS = 32_000
SONNET_API_KEY_ENV = "ANTHROPIC_API_KEY"
SONNET_CLIENT_NAME = "AnthropicSonnet"
SONNET_EFFORTS = ("low", "medium", "high", "xhigh", "max")


ContextMode = Literal["sampled", "full", "compare"]


SonnetEffort = Literal["low", "medium", "high", "xhigh", "max"]


def _sonnet_client_registry(effort: SonnetEffort) -> ClientRegistry:
    registry = ClientRegistry()
    api_key = os.environ.get(SONNET_API_KEY_ENV)
    if not api_key:
        raise click.ClickException(f"{SONNET_API_KEY_ENV} is unset")
    registry.add_llm_client(
        SONNET_CLIENT_NAME,
        "anthropic",
        {
            "model": SONNET_MODEL,
            "api_key": api_key,
            "max_tokens": SONNET_MAX_TOKENS,
            "output_config": {"effort": effort},
            "http": {
                "connect_timeout_ms": SONNET_CONNECT_TIMEOUT_MS,
                "idle_timeout_ms": SONNET_IDLE_TIMEOUT_MS,
                "request_timeout_ms": SONNET_REQUEST_TIMEOUT_MS,
            },
        },
    )
    return registry


class JevEvaluator:
    """Scores rubric text with Jev. Takes text with private placeholders unresolved and
    resolves them only for the Jev call, so the value never reaches the proposer, the
    run state, or the rubric.yaml write-back."""

    def __init__(
        self,
        provider: Any,
        config,
        resolve: Callable[[str], str] = resolve_private,
    ) -> None:
        self._provider = provider
        self._config = config
        self._resolve = resolve

    def evaluate(self, pairs: list[core.UsablePair], rubric_text: str) -> core.EvaluationResult:
        rubric_text = self._resolve(rubric_text)

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
                p_clear=pc,
                p_a=pa,
            )

        cases = list(map(_eval_one, pairs))
        return core.EvaluationResult.from_cases(cases)


class AnthropicProposer:
    """Calls the generated BAML proposer."""

    def __init__(
        self,
        *,
        costs: core.CommitCosts,
        brier_floor: float,
        context_mode: ContextMode = "sampled",
        client: Any = baml,
        sonnet_effort: SonnetEffort = "medium",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._costs = costs
        self._brier_floor = brier_floor
        self._context_mode = context_mode
        if client is baml:
            self._client = client.with_options(
                client_registry=_sonnet_client_registry(sonnet_effort)
            )
        else:
            self._client = client

    def propose(
        self,
        *,
        current_rubric_text: str,
        labeled_cases: list[core.LabeledCase],
        prior_rounds: list[core.RoundResult],
        case_limit: int | None = None,
        history_limit: int | None = None,
        retry: bool = True,
    ) -> core.RubricProposal:
        mismatch_cases = [c for c in labeled_cases if c.jev_prediction != c.expected]
        agree_cases = [c for c in labeled_cases if c.jev_prediction == c.expected]
        structured_rubric_text = self._structure_rubric_text(current_rubric_text)

        from screen.extract.prompt import PRIVATE_PLACEHOLDERS
        private_vals = []
        for name in PRIVATE_PLACEHOLDERS:
            if name in current_rubric_text:
                val = os.environ.get(name, "(not set in environment)")
                private_vals.append(f"{name}: {val}")
        
        if private_vals:
            private_values_text = "\n      ".join(private_vals)
        else:
            private_values_text = None
        
        kwargs = {
            "current_rubric_text": structured_rubric_text,
            "current_cases_text": self._build_cases_text(
                mismatch_cases, agree_cases, limit=case_limit
            ),
            "history_text": self._build_history_text(prior_rounds, limit=history_limit),
            "scoring_rule_text": self.scoring_rule_text(),
            "private_values_text": private_values_text,
        }
        generated = self._call(kwargs, retry=retry)
        return core.RubricProposal(
            theory=generated.theory,
            expected_effect=generated.expected_effect,
            definition=generated.definition,
            fit_anchor_poor=generated.fit_anchor_poor,
            fit_anchor_mixed=generated.fit_anchor_mixed,
            fit_anchor_strong=generated.fit_anchor_strong,
            look_for=generated.look_for,
        )

    def _call(self, kwargs: dict[str, Any], *, retry: bool) -> Any:
        attempts = 3 if retry else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = self._clock()
            try:
                return self._client.ProposeRubricEdit(**kwargs)
            except Exception as exc:
                last_error = exc
                if retry:
                    meta = self._prompt_meta(kwargs)
                    click.echo(
                        (
                            f"[recalibrate] ProposeRubricEdit attempt {attempt}/{attempts} "
                            f"failed after {self._clock() - started:.0f}s: "
                            f"cases={meta['cases_chars']} chars, "
                            f"history={meta['history_chars']} chars, "
                            f"prompt={meta['prompt_chars']} chars, error={exc}"
                        ),
                        err=True,
                    )
                if "contains no text" not in str(exc) or not retry:
                    raise
        assert last_error is not None
        raise click.ClickException(
            f"ProposeRubricEdit failed after {attempts} attempts: {last_error}"
        )
    @staticmethod
    def _structure_rubric_text(rubric_text: str) -> str:
        """Render the target dimension as the same field names the proposer writes back.

        The proposer returns one value per editable field, so it reads them in that
        shape rather than as the rendered prose Jev scores against.
        """
        text = rubric_text.lstrip("\n")
        header, _, _ = text.partition("\n")
        match = re.fullmatch(
            r"### (?P<label>.+) \(slug: (?P<slug>[^,]+), weight: (?P<weight>\d+)\)",
            header.strip(),
        )
        if not match:
            raise ValueError(f"rubric text does not start with a dimension heading: {header!r}")
        data = yaml.safe_load(_RUBRIC_PATH.read_text(encoding="utf-8"))
        target = match.group("slug")
        dim = next((d for d in data.get("dimensions", []) if d.get("slug") == target), None)
        if dim is None:
            raise ValueError(f"rubric.yaml has no dimension with slug {target!r}")
        anchors = dim.get("fit_anchors", {})
        payload = {
            "definition": str(dim.get("definition", "")).strip(),
            "fit_anchor_poor": str(anchors.get("Poor", "")).strip(),
            "fit_anchor_mixed": str(anchors.get("Mixed", "")).strip(),
            "fit_anchor_strong": str(anchors.get("Strong", "")).strip(),
            "look_for": str(dim.get("look_for", "")).strip(),
        }
        return yaml.safe_dump(
            payload,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=4096,
        ).rstrip()

    def scoring_rule_text(self) -> str:
        """The acceptance rule as the proposer reads it, with this run's numbers."""
        return (
            "Jev re-scores every case under your text, and the candidate replaces the\n"
            "current text only if it wins on these, in order:\n"
            "1. net = (right+sure) "
            f"- {self._costs.k_winner:.2f} x (wrong+sure a/b calls) "
            f"- {self._costs.k_tie:.2f} x (wrong+sure tie calls). Higher wins.\n"
            "   A sure call saves the operator a look; a wrong sure call is a silent\n"
            "   error that costs several. Unsure cases don't count: the operator reviews\n"
            "   those whether jev was right or not.\n"
            "2. Mean Brier score (lower wins): how far jev's probabilities sit from the\n"
            "   operator's ruling. p_ruling in each case is the probability jev put on\n"
            "   the operator's ruling; raising it on any case helps, including on\n"
            "   unsure cases and agreements. A change counts only beyond "
            f"{self._brier_floor:.4f},\n"
            "   jev's run-to-run jitter.\n"
            "3. Shorter rubric text. When net is tied, brevity trades off against Brier: "
            "saving 100 characters is worth +0.01 Brier points. Adding bloat requires a "
            "proportional Brier improvement to justify it. Trimming fat (removing unused "
            "guidance) while maintaining accuracy is a valid way to win."
        )

    @staticmethod
    def _prompt_meta(kwargs: dict[str, Any]) -> dict[str, int]:
        cases = str(kwargs.get("current_cases_text", ""))
        history = str(kwargs.get("history_text", ""))
        rubric = str(kwargs.get("current_rubric_text", ""))
        return {
            "cases_chars": len(cases),
            "history_chars": len(history),
            "prompt_chars": len(rubric) + len(cases) + len(history),
        }

    def _build_cases_text(
        self,
        mismatch_cases: list[core.LabeledCase],
        agree_cases: list[core.LabeledCase],
        *,
        limit: int | None = None,
    ) -> str:
        def _fmt_cases(cases: list[core.LabeledCase], n: int) -> str:
            out: list[str] = []
            for c in cases[:n]:
                out.append(
                    f"pair={c.pair_id} expected={c.expected} jev={c.jev_prediction} "
                    f"sure={c.sure} conf={c.jev_confidence:.2f} p_ruling={c.p_ruling:.2f}\n"
                    f"A: {c.digest_a}\nB: {c.digest_b}"
                )
            return "\n---\n".join(out) if out else "(none)"

        mismatch_limit = len(mismatch_cases) if self._context_mode == "full" else 10
        agree_limit = len(agree_cases) if self._context_mode == "full" else 5
        if limit is not None:
            mismatch_limit = min(mismatch_limit, limit)
            agree_limit = min(agree_limit, limit)
        return (
            f"## Mismatches ({len(mismatch_cases)} cases)\n"
            f"{_fmt_cases(mismatch_cases, mismatch_limit)}\n\n"
            f"## Agreements ({len(agree_cases)} cases)\n"
            f"{_fmt_cases(agree_cases, agree_limit)}"
        )

    def _build_history_text(
        self, prior_rounds: list[core.RoundResult], *, limit: int | None = None
    ) -> str:
        if not prior_rounds:
            return "(none)"

        rounds = prior_rounds if limit is None else prior_rounds[:limit]
        parts: list[str] = []
        for round_result in rounds:
            fixed = self._format_pair_block("Fixed", round_result.fixed_cases)
            broken = self._format_pair_block("Broken", round_result.broken_cases)
            parts.append(
                "\n".join(
                    [
                        f"Round {round_result.round_num}",
                        f"Theory: {round_result.theory}",
                        f"Expected effect: {round_result.expected_effect or '(not stated)'}",
                        f"Train: {round_result.train_buckets}",
                        f"Train net: {round_result.train_net:.2f}  "
                        f"mean Brier: {round_result.train_brier:.4f}  "
                        f"Draft length: {len(round_result.candidate_rubric_text.strip())} chars",
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
                f"sure={c.sure} conf={c.jev_confidence:.2f} p_ruling={c.p_ruling:.2f}\n"
                f"  A: {c.digest_a}\n  B: {c.digest_b}"
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
@click.option(
    "--sonnet-effort",
    type=click.Choice(list(SONNET_EFFORTS), case_sensitive=False),
    default="medium",
    show_default=True,
    help="Anthropic Sonnet thinking effort for the proposer.",
)
@click.option(
    "--probe-baml",
    is_flag=True,
    default=False,
    help="Halve the prompt window and call the proposer directly up to a small cap, to check whether empty-text failures correlate with prompt size.",
)
@click.option(
    "--probe-baml-bisects",
    type=int,
    default=8,
    show_default=True,
    help="Maximum prompt-size halvings to attempt in probe mode.",
)
def recalibrate(
    target: str,
    rounds: int,
    floor: int,
    seed: int,
    db_path: Path | None,
    context_mode: ContextMode,
    state_path: Path | None,
    sonnet_effort: SonnetEffort,
    probe_baml: bool,
    probe_baml_bisects: int,
) -> None:
    """Propose rubric edits for TARGET and measure them on held-out pairs.

    Leaves the winning candidate applied to rubric.yaml but never commits it.
    """
    config = load_scoring_config()

    if context_mode == "compare":
        _run_compare_mode(
            target=target,
            rounds=rounds,
            floor=floor,
            seed=seed,
            db_path=db_path,
            config=config,
            sonnet_effort=sonnet_effort,
        )
        return

    run_dir = state_path.parent if state_path else runstate.default_run_dir(target)
    evaluator = JevEvaluator(JevVerdictProvider(config, TypeSafeClient()), config)
    costs = _commit_costs(config)

    if (run_dir / "state.json").exists():
        try:
            state = runstate.load_state(run_dir / "state.json")
            runstate.require_baseline_unchanged(state, unresolved_rubric_text_for_dimension(target))
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

    proposer = AnthropicProposer(
        costs=costs,
        brier_floor=state.brier_noise_floor,
        context_mode=context_mode,
        sonnet_effort=sonnet_effort,
    )
    if probe_baml:
        _probe_baml_prompt(state=state, proposer=proposer, max_halvings=probe_baml_bisects)
        return

    if rounds > 0:
        click.echo(f"\n  Running {rounds} more round(s) with {context_mode} context…\n")
        core.run_rounds(
            propose_pairs=state.propose_pairs,
            held_pairs=state.held_pairs,
            current_rubric_text=state.current_rubric_text,
            proposer=proposer,
            evaluator=evaluator,
            costs=costs,
            brier_floor=state.brier_noise_floor,
            n_rounds=rounds,
            baseline_train=state.current_train,
            round_offset=state.rounds_completed,
            on_round_start=lambda round_num: click.echo(f"  [round {round_num}] starting…"),
            on_stage_done=lambda round_num, stage, elapsed: click.echo(
                f"  [round {round_num}] {stage} done in {elapsed:.1f}s"
            ),
            on_round=lambda result: runstate.record_round(state, result),
        )

    _print_results(state, costs)
    _maybe_apply_winner(target, state, costs)


def _commit_costs(config) -> core.CommitCosts:
    return core.CommitCosts.from_thresholds(
        winner_commit_threshold=config.winner_commit_threshold,
        tie_commit_threshold=config.tie_commit_threshold,
    )


def _score_line(cases: list[core.LabeledCase], costs: core.CommitCosts) -> str:
    score = core.Score.of(cases, costs)
    return f"net {score.net:.2f}  mean Brier {score.brier:.4f}"


def _probe_baml_prompt(
    *,
    state: runstate.RunState,
    proposer: AnthropicProposer,
    max_halvings: int,
) -> None:
    """Exercise the BAML proposer directly with progressively smaller prompt windows.

    This is a debugging aid: if the empty-text failure correlates with prompt size,
    the run will stop reproducing when the case/history window is small enough.
    """
    cases = list(state.current_train.cases)
    prior_rounds = list(state.rounds)
    full_window = max(len(cases), len(prior_rounds), 1)

    click.echo(
        f"[probe] {state.target}: cases={len(cases)} rounds={len(prior_rounds)} "
        f"starting_window={full_window} max_halvings={max_halvings}"
    )
    window = full_window
    for step in range(1, max_halvings + 1):
        cases_text = proposer._build_cases_text(
            [c for c in cases if c.jev_prediction != c.expected],
            [c for c in cases if c.jev_prediction == c.expected],
            limit=window,
        )
        history_text = proposer._build_history_text(prior_rounds, limit=window)
        prompt_bytes = len(state.current_rubric_text.encode("utf-8"))
        prompt_bytes += len(cases_text.encode("utf-8"))
        prompt_bytes += len(history_text.encode("utf-8"))
        click.echo(
            f"[probe] step {step}/{max_halvings}: window={window} prompt_bytes={prompt_bytes}"
        )
        try:
            generated = proposer._call(
                {
                    "current_rubric_text": state.current_rubric_text,
                    "current_cases_text": cases_text,
                    "history_text": history_text,
                    "scoring_rule_text": proposer.scoring_rule_text(),
                    "private_values_text": "(not relevant in probe mode)",
                },
                retry=False,
            )
        except Exception as exc:
            click.echo(f"[probe] step {step}: failure -> {exc}", err=True)
            if window == 1:
                click.echo("[probe] reached window=1; aborting probe")
                return
            window = max(1, window // 2)
            continue

        click.echo(
            f"[probe] step {step}: success -> theory={generated.theory!r}, "
            f"expected_effect={generated.expected_effect!r}"
        )
        if window == 1:
            return
        window = max(1, window // 2)


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

    rubric_text = unresolved_rubric_text_for_dimension(target)
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
    click.echo(f"  Brier noise floor: {state.brier_noise_floor:.4f}")
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
    sonnet_effort: SonnetEffort,
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
    costs = _commit_costs(config)
    rubric_text = unresolved_rubric_text_for_dimension(target)
    t0 = time.monotonic()
    baseline_train = evaluator.evaluate(propose_pairs, rubric_text)
    click.echo(f"  baseline train ({time.monotonic() - t0:.1f}s): {baseline_train.buckets}")
    t0 = time.monotonic()
    baseline_noise = evaluator.evaluate(propose_pairs, rubric_text)
    click.echo(f"  baseline noise ({time.monotonic() - t0:.1f}s): {baseline_noise.buckets}")
    brier_floor = core.brier_noise_floor(baseline_train, baseline_noise)
    t0 = time.monotonic()
    baseline_held = evaluator.evaluate(held_pairs, rubric_text)
    click.echo(f"  baseline held-out ({time.monotonic() - t0:.1f}s): {baseline_held.buckets}")
    click.echo("\n  Comparing sampled and full-context runs…")
    click.echo(f"  baseline train: {baseline_train.buckets}")
    click.echo(f"  baseline held-out: {baseline_held.buckets}")
    for mode in ("sampled", "full"):
        proposer = AnthropicProposer(
            costs=costs,
            brier_floor=brier_floor,
            context_mode=mode,
            sonnet_effort=sonnet_effort,
        )
        click.echo(f"\n  [{mode}] Running {rounds} round(s)…\n")
        results = core.run_rounds(
            propose_pairs=propose_pairs,
            held_pairs=held_pairs,
            current_rubric_text=rubric_text,
            proposer=proposer,
            evaluator=evaluator,
            costs=costs,
            brier_floor=brier_floor,
            n_rounds=rounds,
            baseline_train=baseline_train,
            on_round_start=lambda round_num: click.echo(
                f"  [{mode}] [round {round_num}] starting…"
            ),
            on_stage_done=lambda round_num, stage, elapsed: click.echo(
                f"  [{mode}] [round {round_num}] {stage} done in {elapsed:.1f}s"
            ),
        )
        for r in results:
            click.echo(f"  [{mode}] Round {r.round_num}: {r.theory}")
            click.echo(f"    expect:   {r.expected_effect}")
            click.echo(f"    train:    {r.train_buckets}")
            click.echo(f"    train cm: {core.ConfusionMatrix.from_cases(r.train_cases or [])}")
            click.echo(f"    held-out: {r.held_out_buckets}")
            click.echo(f"    score:    train {_score_line(r.train_cases or [], costs)}")
            click.echo(f"              held  {_score_line(r.held_out_cases or [], costs)}")
            click.echo(f"    accepted: {r.accepted}")
        winner = core.best_round(results)
        if winner is None:
            click.echo(f"  [{mode}] No candidate was accepted — no edit proposed.")
        else:
            click.echo(f"  [{mode}] best train: {winner.train_buckets}")
            click.echo(f"  [{mode}] best held:  {winner.held_out_buckets}")


def _print_results(state: runstate.RunState, costs: core.CommitCosts) -> None:
    click.echo(
        f"\n[recalibrate] {state.target}: {state.rounds_completed} round(s) recorded in {state.state_path}"
    )
    click.echo(f"  baseline train: {state.baseline_train.buckets}")
    click.echo(f"  baseline score: {_score_line(state.baseline_train.cases, costs)}")
    click.echo(f"  Brier noise floor: {state.brier_noise_floor:.4f}")
    click.echo(f"  commit costs: k_winner {costs.k_winner:.2f}  k_tie {costs.k_tie:.2f}")
    for r in state.rounds:
        click.echo(f"\n  Round {r.round_num}: {r.theory}")
        click.echo(f"    expect:   {r.expected_effect}")
        click.echo(f"    train:    {r.train_buckets}")
        click.echo(f"    train cm: {core.ConfusionMatrix.from_cases(r.train_cases or [])}")
        click.echo(f"    held-out: {r.held_out_buckets}")
        click.echo(f"    score:    train {_score_line(r.train_cases or [], costs)}")
        click.echo(f"              held  {_score_line(r.held_out_cases or [], costs)}")
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


def _maybe_apply_winner(target: str, state: runstate.RunState, costs: core.CommitCosts) -> None:
    # --- Final Readout Summary ---
    click.echo("\n" + "=" * 40)
    click.echo("RECALIBRATION RUN SUMMARY")
    click.echo("=" * 40)
    click.echo(f"Baseline Score: {_score_line(state.baseline_train.cases, costs)}")
    click.echo("\nTrajectory:")
    
    best_net = costs.net(state.baseline_train.cases)
    best_brier = core.mean_brier(state.baseline_train.cases)
    
    for r in state.rounds:
        status = "✅ ACCEPTED" if r.accepted else "❌ REJECTED"
        train_net = r.train_net or 0.0
        train_brier = r.train_brier or 0.0
        
        # truncate theory for readability in summary
        theory = r.theory or ""
        if len(theory) > 120:
            theory = theory[:117] + "..."
            
        click.echo(f"  Round {r.round_num}: {status} (net {train_net:+.2f}, brier {train_brier:.4f})")
        click.echo(f"    Theory: {theory}")
        
        if r.accepted:
            best_net = train_net
            best_brier = train_brier

    click.echo(f"\nFinal Best Score: net {best_net:+.2f}, brier {best_brier:.4f}")
    click.echo("=" * 40 + "\n")
    winner = core.best_round(state.rounds)
    if winner is None:
        click.echo(
            "\n[recalibrate] No candidate beat the current best — no edit proposed. "
            "rubric.yaml unchanged."
        )
        return
    apply_candidate(target, winner.candidate_rubric_text)
    click.echo("\nrubric.yaml updated (not committed). Review with `git diff rubric.yaml`.")


def _rubric_dump(doc: dict) -> str:
    """Serialize a rubric document to stable, comment-free YAML.
    - Multi-line strings → literal block scalar (|): no trailing newlines, no wrapping.
    - Strings containing apostrophes → double-quote style: no '' escaping.
    - Strings starting with a YAML indicator char → double-quote style.
    - Everything else → plain scalar.
    - width=4096: single-line strings are never wrapped (no backslash continuations).
    - sort_keys=True for all keys EXCEPT fit_anchors, which is always Poor/Mixed/Strong.

    Round-trips cleanly: strip() on every string value is idempotent.
    """
    _FIT_ANCHOR_ORDER = ["Poor", "Mixed", "Strong"]

    def _strip(obj):
        if isinstance(obj, str):
            return obj.strip()
        if isinstance(obj, dict):
            return {k: _strip(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_strip(v) for v in obj]
        return obj

    def _normalize(obj):
        """Sort non-fit-anchor dicts by key; fix fit_anchor order to Poor/Mixed/Strong."""
        if isinstance(obj, list):
            return [_normalize(v) for v in obj]
        if isinstance(obj, dict):
            if set(obj.keys()) <= set(_FIT_ANCHOR_ORDER) and obj:
                return {k: _normalize(obj[k]) for k in _FIT_ANCHOR_ORDER if k in obj}
            return {k: _normalize(obj[k]) for k in sorted(obj.keys())}
        return obj

    def _str_representer(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        if "'" in data or (data and data[0] in ">|&*!{}[]#,%-"):
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=None)

    class _Dumper(yaml.Dumper):  # type: ignore[misc]
        pass

    _Dumper.add_representer(str, _str_representer)
    cleaned = _normalize(_strip(doc))
    return yaml.dump(
        cleaned,
        Dumper=_Dumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,  # pre-sorted by _normalize; sort_keys=True would override fit_anchor order
        width=4096,
    )


def apply_candidate(slug: str, candidate_text: str, *, rubric_path: Path | None = None) -> str:
    """Write a winning candidate back into rubric.yaml and return the git diff.
    rehydrate partial proposals — so what lands in YAML is exactly what was measured.
    The file is serialised with `_rubric_dump`, which produces stable, comment-free YAML;
    subsequent runs that win a new candidate produce minimal diffs.
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
    rubric_path.write_text(_rubric_dump(doc), encoding="utf-8")
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
