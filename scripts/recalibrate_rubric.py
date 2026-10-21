"""CLI for the rubric recalibration loop.

The testable core lives in `screen.recalibration`; this file owns the live
Anthropic proposer, Jev-backed evaluation, and the command-line glue.

Run it as a file path or a dotted module — `-m` will not accept a `.py` suffix:

    uv run python scripts/recalibrate_rubric.py --target location
    uv run python -m scripts.recalibrate_rubric --target location
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
import click
import yaml
from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient
from typing import Literal, Protocol

from screen import recalibration as core
from screen.extract.prompt import rubric_text_for_dimension
from screen.score.loader import load_scoring_config
from screen.verdict.jev_verdict_provider import JevVerdictProvider

load_dotenv(Path(__file__).parent.parent / ".env")

_RUBRIC_PATH = Path(__file__).parent.parent / "rubric.yaml"
_TIE_BOUNDARY = 0.5
_SURE_THRESHOLD = 0.70
ContextMode = Literal["sampled", "full"]


def _decide(pc: float, pa: float) -> tuple[str, float]:
    if pc < _TIE_BOUNDARY:
        return "tie", 1 - pc
    pred = "a" if pa >= _TIE_BOUNDARY else "b"
    return pred, pc * (pa if pred == "a" else 1 - pa)


class JevEvaluator:
    def __init__(self, provider: JevVerdictProvider) -> None:
        self._provider = provider

    def evaluate(self, pairs: list[core.UsablePair], rubric_text: str) -> core.BucketCounts:
        def _eval_one(pair: core.UsablePair) -> tuple[str, float]:
            fwd = self._provider.get_ruling(rubric_text, pair.digest_a, pair.digest_b, [])
            rev = self._provider.get_ruling(rubric_text, pair.digest_b, pair.digest_a, [])
            pc = (fwd.clear_winner.p_true + rev.clear_winner.p_true) / 2
            pa = (fwd.a_is_better.p_true + (1 - rev.a_is_better.p_true)) / 2
            return _decide(pc, pa)

        counts = core.BucketCounts()
        with ThreadPoolExecutor(max_workers=12) as ex:
            results = list(ex.map(_eval_one, pairs))
        for (pred, conf), pair in zip(results, pairs, strict=True):
            right = pred == pair.expected
            sure = conf >= _SURE_THRESHOLD
            if right and sure:
                counts.right_sure += 1
            elif right:
                counts.right_unsure += 1
            elif sure:
                counts.wrong_sure += 1
            else:
                counts.wrong_unsure += 1
        return counts


class AnthropicProposer:
    """Calls Claude Sonnet to propose a minimal rubric rewrite."""

    _SYSTEM = """You are a rubric editor for a job-screener system.
Your job is to propose a minimal edit to one scoring dimension's rubric text that would
bring the evaluator's predictions closer to the operator's rulings.

Rules:
- Output ONLY the revised rubric text for the dimension. Do not add preamble or
  explanation outside the rubric text itself.
- On the very first line, write a comment starting with `# theory:` explaining in one
  sentence what pattern you are trying to fix and why.
- Make the smallest possible change. Prefer adding a sentence over rewriting an anchor.
  Never rewrite the entire rubric.
- Never include dollar amounts, salary figures, or specific compensation values.
- If you genuinely believe the rubric is not the problem (missing operator data, not
  wording), output the current rubric unchanged and write
  `# theory: no wording defect found — pattern looks like missing data`.
"""

    def __init__(self, model: str = "claude-sonnet-5", context_mode: ContextMode = "sampled") -> None:
        self._model = model
        self._context_mode = context_mode
        self._client = anthropic.Anthropic()

    def propose(
        self,
        *,
        current_rubric_text: str,
        labeled_cases: list[core.LabeledCase],
        prior_rounds: list[core.RoundResult],
    ) -> str:
        mismatch_cases = [c for c in labeled_cases if c.jev_prediction != c.expected]
        agree_cases = [c for c in labeled_cases if c.jev_prediction == c.expected]
        prior_text = ""
        if prior_rounds:
            prior_text = "\n\nPrior rounds:\n" + "\n".join(
                f"Round {r.round_num} theory: {r.theory}\nHeld-out result: {r.held_out_buckets}"
                for r in prior_rounds
            )
        message = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": self._build_prompt(
                        current_rubric_text,
                        mismatch_cases,
                        agree_cases,
                        prior_text,
                        self._context_mode,
                    ),
                }
            ],
        )
        return _message_text(message)

    def _build_prompt(
        self,
        current_rubric_text: str,
        mismatch_cases: list[core.LabeledCase],
        agree_cases: list[core.LabeledCase],
        prior_text: str,
        context_mode: ContextMode,
    ) -> str:
        def _fmt_cases(cases: list[core.LabeledCase], n: int) -> str:
            out: list[str] = []
            for c in cases[:n]:
                out.append(
                    f"expected={c.expected}  jev={c.jev_prediction}  conf={c.jev_confidence:.2f}\n"
                    f"A: {c.digest_a[:120]}\nB: {c.digest_b[:120]}"
                )
            return "\n---\n".join(out) if out else "(none)"

        mismatch_limit = len(mismatch_cases) if context_mode == "full" else 10
        agree_limit = len(agree_cases) if context_mode == "full" else 5
        return (
            f"## Current rubric text\n{current_rubric_text}\n\n"
            f"## Mismatches ({len(mismatch_cases)} cases)\n{_fmt_cases(mismatch_cases, mismatch_limit)}\n\n"
            f"## Agreements ({len(agree_cases)} cases)\n{_fmt_cases(agree_cases, agree_limit)}\n"
            f"{prior_text}\n\nPropose a revised rubric text for this dimension."
        )


def _message_text(message: object) -> str:
    content = getattr(message, "content", [])
    return "".join(getattr(block, "text", "") for block in content if getattr(block, "type", None) == "text")

def _build_labeled_cases(
    pairs: list[core.UsablePair], rubric_text: str, provider: JevVerdictProvider
) -> list[core.LabeledCase]:
    def _eval_one(pair: core.UsablePair) -> tuple[str, float]:
        fwd = provider.get_ruling(rubric_text, pair.digest_a, pair.digest_b, [])
        rev = provider.get_ruling(rubric_text, pair.digest_b, pair.digest_a, [])
        pc = (fwd.clear_winner.p_true + rev.clear_winner.p_true) / 2
        pa = (fwd.a_is_better.p_true + (1 - rev.a_is_better.p_true)) / 2
        return _decide(pc, pa)

    with ThreadPoolExecutor(max_workers=12) as ex:
        evals = list(ex.map(_eval_one, pairs))
    return [
        core.LabeledCase(
            digest_a=p.digest_a,
            digest_b=p.digest_b,
            expected=p.expected,
            jev_prediction=pred,
            jev_confidence=conf,
        )
        for p, (pred, conf) in zip(pairs, evals, strict=True)
    ]


def _candidate_body_lines(candidate_text: str) -> list[str]:
    lines = [line.rstrip() for line in candidate_text.splitlines() if line.strip()]
    if lines and lines[0].startswith("# theory:"):
        lines = lines[1:]
    if not lines or not lines[0].startswith("### "):
        raise click.ClickException("candidate text is missing the dimension heading")
    return lines


def _parse_fit_anchor_lines(lines: list[str]) -> dict[str, str]:
    fit_anchors: dict[str, str] = {}
    current_anchor: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_anchor, current_parts
        if current_anchor is not None:
            fit_anchors[current_anchor] = " ".join(part.strip() for part in current_parts).strip()
        current_anchor = None
        current_parts = []

    for line in lines:
        stripped = line.strip()
        if line.startswith("  ") and ":" in stripped:
            flush()
            current_anchor, rest = stripped.split(":", 1)
            current_parts = [rest.strip()]
            continue
        if current_anchor is None:
            raise click.ClickException("candidate fit anchors are malformed")
        current_parts.append(stripped)
    flush()
    return fit_anchors


def _parse_dimension_candidate(candidate_text: str) -> tuple[str, dict[str, str], str | None]:
    lines = _candidate_body_lines(candidate_text)
    fit_anchor_index = lines.index("Fit anchors:")
    look_for_index = next(
        (i for i, line in enumerate(lines) if line.startswith("Look for:")),
        len(lines),
    )

    definition = "\n".join(lines[1:fit_anchor_index]).strip()
    fit_anchors = _parse_fit_anchor_lines(lines[fit_anchor_index + 1 : look_for_index])
    look_for = None
    if look_for_index < len(lines):
        look_for = lines[look_for_index].split(":", 1)[1].strip()
        tail = [line.strip() for line in lines[look_for_index + 1 :]]
        if tail:
            look_for = f"{look_for} {' '.join(tail)}".strip()
    return definition, fit_anchors, look_for


def apply_candidate(slug: str, candidate_text: str) -> str:
    raw = _RUBRIC_PATH.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    definition, fit_anchors, look_for = _parse_dimension_candidate(candidate_text)
    for dim in doc.get("dimensions", []):
        if dim.get("slug") == slug:
            dim["definition"] = definition
            if fit_anchors:
                dim["fit_anchors"] = fit_anchors
            if look_for is not None:
                dim["look_for"] = look_for
            break
    new_yaml = yaml.dump(doc, allow_unicode=True, default_flow_style=False, sort_keys=False)
    _RUBRIC_PATH.write_text(new_yaml, encoding="utf-8")
    result = subprocess.run(
        ["git", "diff", "rubric.yaml"],
        cwd=_RUBRIC_PATH.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


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
def recalibrate(
    target: str, rounds: int, floor: int, seed: int, db_path: Path | None, context_mode: str
) -> None:
    """Propose rubric edits for TARGET and measure them on held-out pairs.

    Leaves the winning candidate applied to rubric.yaml but never commits it.
    """
    conn = _open_db(db_path)
    config = load_scoring_config()

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
    evaluator = JevEvaluator(provider)
    rubric_text = rubric_text_for_dimension(target)
    labeled_cases = _build_labeled_cases(propose_pairs, rubric_text, provider)

    click.echo("\n  Measuring baseline on propose split…")
    baseline_train = evaluator.evaluate(propose_pairs, rubric_text)
    click.echo(f"  baseline train: {baseline_train}")
    click.echo("  Measuring baseline on held-out pairs…")
    baseline_held = evaluator.evaluate(held_pairs, rubric_text)
    click.echo(f"  baseline held-out: {baseline_held}")

    if context_mode == "compare":
        click.echo("\n  Comparing sampled and full-context runs…")
        click.echo(f"  baseline train: {baseline_train}")
        click.echo(f"  baseline held-out: {baseline_held}")
        for mode in ("sampled", "full"):
            proposer = AnthropicProposer(context_mode=mode)
            click.echo(f"\n  [{mode}] Running {rounds} round(s)…\n")
            results = core.run_rounds(
                propose_pairs=propose_pairs,
                held_pairs=held_pairs,
                labeled_cases=labeled_cases,
                current_rubric_text=rubric_text,
                proposer=proposer,
                evaluator=evaluator,
                n_rounds=rounds,
                baseline_train=baseline_train,
            )
            for r in results:
                click.echo(f"  [{mode}] Round {r.round_num}: {r.theory}")
                click.echo(f"    train:    {r.train_buckets}")
                click.echo(f"    held-out: {r.held_out_buckets}")
            winner = core.best_round(results, baseline_train, rubric_text)
            if winner is None:
                click.echo(
                    f"  [{mode}] No candidate beat the training objective — no edit proposed."
                )
            else:
                click.echo(f"  [{mode}] best train: {winner.train_buckets}")
                click.echo(f"  [{mode}] best held:  {winner.held_out_buckets}")
        return

    proposer = AnthropicProposer(context_mode=context_mode)
    click.echo(f"\n  Running {rounds} round(s) with {context_mode} context…\n")
    results = core.run_rounds(
        propose_pairs=propose_pairs,
        held_pairs=held_pairs,
        labeled_cases=labeled_cases,
        current_rubric_text=rubric_text,
        proposer=proposer,
        evaluator=evaluator,
        n_rounds=rounds,
        baseline_train=baseline_train,
    )
    for r in results:
        click.echo(f"  Round {r.round_num}: {r.theory}")
        click.echo(f"    train:    {r.train_buckets}")
        click.echo(f"    held-out: {r.held_out_buckets}")
    winner = core.best_round(results, baseline_train, rubric_text)
    if winner is None:
        click.echo(
            "\n[recalibrate] No candidate beat the training objective — no edit proposed. "
            "rubric.yaml unchanged."
        )
        click.echo(f"  held-out baseline indicator: {baseline_held}")
        return
    click.echo(f"  baseline train: {baseline_train}")
    click.echo(f"  baseline held:  {baseline_held}")
    click.echo(f"  candidate train:{winner.train_buckets}")
    click.echo(f"  candidate held: {winner.held_out_buckets}")
    diff = apply_candidate(target, winner.candidate_rubric_text)
    click.echo("\n--- rubric.yaml diff ---")
    click.echo(diff or "(no structural change — definition was functionally identical)")
    click.echo("--- end diff ---")
    click.echo("\nrubric.yaml updated (not committed). Review with `git diff rubric.yaml`.")


if __name__ == "__main__":
    recalibrate()
