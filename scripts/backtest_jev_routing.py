"""Backtest Jev's routing policy on operator comparisons.
and can optionally print the individual mismatches for a chosen threshold pair.
"""
# ruff: noqa: I001, E402

from __future__ import annotations
import argparse
from dotenv import load_dotenv
import os
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from itertools import product
from typesafe_sdk import TypeSafeClient
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from screen.extract.prompt import rubric_text_for_dimension
from screen.score.loader import load_scoring_config
from screen.store.repo import comparisons_for_target, get_dimension_digest
from screen.verdict.jev_verdict_provider import JevVerdictProvider
from screen.verdict.protocol import JevRuling
from screen.verdict.routing import route_verdict

DEFAULT_TARGETS = ["location", "craft_direction", "schematic", "mission", "internal_culture"]

TIE_THRESHOLDS = [0.80, 0.85, 0.90, 0.92, 0.95]
WINNER_THRESHOLDS = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


@dataclass(frozen=True)
class Case:
    target: str
    opening_a_id: str
    opening_b_id: str
    expected: str
    ruling: JevRuling


@dataclass(frozen=True)
class ThresholdResult:
    tie_threshold: float
    winner_threshold: float
    total: int
    auto_commit: int
    routed: int
    correct: int
    predicted_counts: Counter[str]
    actual_counts: Counter[str]
    correct_by_outcome: Counter[str]
    wrong_by_predicted: Counter[str]
    mismatches: list[Case]

    @property
    def auto_precision(self) -> float:
        return self.correct / self.auto_commit if self.auto_commit else 0.0

    @property
    def auto_recall(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def precision_for(self, outcome: str) -> float:
        predicted = self.predicted_counts[outcome]
        return self.correct_by_outcome[outcome] / predicted if predicted else 0.0

    def recall_for(self, outcome: str) -> float:
        actual = self.actual_counts[outcome]
        return self.correct_by_outcome[outcome] / actual if actual else 0.0


@dataclass(frozen=True)
class TargetLoadStats:
    target: str
    considered: int
    loaded: int
    skipped_missing_digests: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest Jev's routing policy on operator comparisons. "
            "Reports how often the routing function would auto-commit versus route to the operator."
        )
    )
    parser.add_argument("db_path", nargs="?", default="data/live/screen.db")
    parser.add_argument("--target", action="append", dest="targets", help="dimension slug to evaluate")
    parser.add_argument("--max-workers", type=int, default=10)
    parser.add_argument("--limit-per-target", type=int, default=None)
    parser.add_argument(
        "--show-mismatches",
        action="store_true",
        help="Print mismatched auto-commits for the default threshold pair.",
    )
    return parser.parse_args()


def _load_cases(
    conn: sqlite3.Connection, targets: list[str], provider: JevVerdictProvider, limit_per_target: int | None
) -> tuple[list[Case], list[TargetLoadStats]]:
    cases: list[Case] = []
    stats: list[TargetLoadStats] = []
    for target in targets:
        rubric_text = rubric_text_for_dimension(target)
        comparisons = [c for c in comparisons_for_target(conn, target) if c.provenance == "operator"]
        considered = len(comparisons)
        if limit_per_target is not None:
            comparisons = comparisons[:limit_per_target]
        loaded = 0
        skipped_missing = 0
        for comparison in comparisons:
            digest_a = get_dimension_digest(conn, comparison.opening_a_id, target)
            digest_b = get_dimension_digest(conn, comparison.opening_b_id, target)
            if digest_a is None or digest_b is None:
                skipped_missing += 1
                continue
            ruling = provider.get_ruling(rubric_text, digest_a.digest, digest_b.digest, [])
            cases.append(
                Case(
                    target=target,
                    opening_a_id=comparison.opening_a_id,
                    opening_b_id=comparison.opening_b_id,
                    expected=comparison.outcome,
                    ruling=ruling,
                )
            )
            loaded += 1
        stats.append(
            TargetLoadStats(
                target=target,
                considered=considered,
                loaded=loaded,
                skipped_missing_digests=skipped_missing,
            )
        )
    return cases, stats


def _evaluate_thresholds(cases: list[Case], tie_threshold: float, winner_threshold: float) -> ThresholdResult:
    predicted_counts: Counter[str] = Counter()
    actual_counts: Counter[str] = Counter(case.expected for case in cases)
    correct_by_outcome: Counter[str] = Counter()
    wrong_by_predicted: Counter[str] = Counter()
    mismatches: list[Case] = []

    auto_commit = 0
    correct = 0
    routed = 0

    for case in cases:
        decision = route_verdict(
            case.ruling,
            tie_commit_threshold=tie_threshold,
            winner_commit_threshold=winner_threshold,
        )
        if not decision.auto_commit:
            routed += 1
            continue

        auto_commit += 1
        predicted_counts[decision.verdict.outcome] += 1
        if decision.verdict.outcome == case.expected:
            correct += 1
            correct_by_outcome[case.expected] += 1
        else:
            wrong_by_predicted[decision.verdict.outcome] += 1
            mismatches.append(case)

    return ThresholdResult(
        tie_threshold=tie_threshold,
        winner_threshold=winner_threshold,
        total=len(cases),
        auto_commit=auto_commit,
        routed=routed,
        correct=correct,
        predicted_counts=predicted_counts,
        actual_counts=actual_counts,
        correct_by_outcome=correct_by_outcome,
        wrong_by_predicted=wrong_by_predicted,
        mismatches=mismatches,
    )


def _format_result(result: ThresholdResult) -> str:
    tie_p = result.precision_for("tie") * 100
    tie_r = result.recall_for("tie") * 100
    a_p = result.precision_for("a") * 100
    a_r = result.recall_for("a") * 100
    b_p = result.precision_for("b") * 100
    b_r = result.recall_for("b") * 100
    return (
        f"tie={result.tie_threshold:.2f} winner={result.winner_threshold:.2f} | "
        f"auto {result.auto_commit:4d} ({result.auto_commit / result.total * 100:5.1f}%) | "
        f"route {result.routed:4d} ({result.routed / result.total * 100:5.1f}%) | "
        f"prec {result.auto_precision * 100:5.1f}% recall {result.auto_recall * 100:5.1f}% | "
        f"tie P/R {tie_p:5.1f}/{tie_r:5.1f} | a P/R {a_p:5.1f}/{a_r:5.1f} | b P/R {b_p:5.1f}/{b_r:5.1f} | "
        f"wrong tie/a/b {result.wrong_by_predicted['tie']:3d}/{result.wrong_by_predicted['a']:3d}/{result.wrong_by_predicted['b']:3d}"
    )


def _print_target_load_stats(stats: list[TargetLoadStats]) -> None:
    print("Loaded comparisons by target")
    for stat in stats:
        skipped_label = f", skipped_missing={stat.skipped_missing_digests}" if stat.skipped_missing_digests else ""
        print(
            f"  {stat.target:18} considered={stat.considered:4d} loaded={stat.loaded:4d}{skipped_label}"
        )
    print()


def _print_mismatches(result: ThresholdResult) -> None:
    if not result.mismatches:
        print("No mismatches at the default threshold pair.")
        return
    print("Mismatches at default threshold pair")
    for case in result.mismatches:
        decision = route_verdict(
            case.ruling,
            tie_commit_threshold=result.tie_threshold,
            winner_commit_threshold=result.winner_threshold,
        )
        print(
            f"  {case.target:18} expected={case.expected:4} predicted={decision.verdict.outcome:4} "
            f"auto={decision.auto_commit!s:5} p_true(clear)={case.ruling.clear_winner.p_true:.2f} "
            f"p_true(a)={case.ruling.a_is_better.p_true:.2f} a={case.opening_a_id} b={case.opening_b_id}"
        )


def main() -> int:
    load_dotenv()
    if not os.getenv("TYPESAFE_API_KEY"):
        print("Missing TYPESAFE_API_KEY in environment; Jev evaluation needs it.")
        return 1

    args = _parse_args()
    targets = args.targets or DEFAULT_TARGETS
    scoring_config = load_scoring_config()

    conn = sqlite3.connect(
        f"file:{os.path.abspath(args.db_path)}?mode=ro", uri=True, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    provider = JevVerdictProvider(TypeSafeClient())

    # Warm the provider/client once so the concurrency below only does I/O, not lazy init.
    _ = provider

    cases, load_stats = _load_cases(conn, targets, provider, args.limit_per_target)
    if not cases:
        print("No operator comparisons found.")
        return 0

    print(f"Evaluated {len(cases)} operator comparisons across {len({case.target for case in cases})} targets")
    print()
    _print_target_load_stats(load_stats)

    default_result = _evaluate_thresholds(
        cases,
        tie_threshold=scoring_config.tie_commit_threshold,
        winner_threshold=scoring_config.winner_commit_threshold,
    )
    print(
        f"Default (tie={scoring_config.tie_commit_threshold:.2f} "
        f"winner={scoring_config.winner_commit_threshold:.2f})"
    )
    print(_format_result(default_result))
    print()

    if args.show_mismatches:
        _print_mismatches(default_result)
        print()

    print("Sweep: asymmetric thresholds")
    for tie_threshold, winner_threshold in product(TIE_THRESHOLDS, WINNER_THRESHOLDS):
        result = _evaluate_thresholds(cases, tie_threshold=tie_threshold, winner_threshold=winner_threshold)
        print(_format_result(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
