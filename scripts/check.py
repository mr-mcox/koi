"""Project discipline gate. Single entry point for all "is the repo ready
to commit?" checks.

When a gate fails, the message includes the standalone command to re-run
that one tool — that is the iteration loop the script can't replace.
"""

import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "screen"
COVERAGE_JSON = REPO_ROOT / "coverage" / "coverage.json"

COVERAGE_TIER_PERCENT = 100
BRANCH_TIER_PERCENT = 100

GENERATED_CODE_DIR = "src/screen/baml_client/"


def _omit_from_coverage() -> list[str]:
    """The `[tool.coverage.run] omit` list, read from pyproject rather than restated.

    Omitted files never appear in coverage data, so the discipline gate can't compute
    their tier and must skip them. Keeping one copy means the two can't drift.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(pyproject["tool"]["coverage"]["run"]["omit"])


OMIT_FROM_COVERAGE: list[str] = _omit_from_coverage()

_TYPE_IGNORE_PATTERNS = [
    re.compile(r"#\s*type:\s*ignore\b"),
    re.compile(r"#\s*pyright:\s*ignore\b"),
    re.compile(r"#\s*noqa\b"),
]

_NO_COVER_PRAGMA = re.compile(r"#\s*pragma:\s*no\s+cover\b(?P<rest>.*)$")
# The reason follows a dash: `# pragma: no cover — <why>`.
_NO_COVER_REASON = re.compile(r"^\s*[—–-]+\s*\S")


def _rel(py_file: Path) -> str:
    return str(py_file.relative_to(REPO_ROOT))


def _is_exempt(rel: str) -> bool:
    return rel.startswith(GENERATED_CODE_DIR) or rel in OMIT_FROM_COVERAGE


def _run(argv: list[str]) -> tuple[bool, list[str]]:
    """Run a subprocess. Return (ok, lines of detail)."""
    result = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return True, []
    output = (result.stdout + result.stderr).strip().splitlines()
    tail = output[-20:] if len(output) > 20 else output
    return False, [f"exit {result.returncode}"] + tail


def _check_pytest() -> tuple[bool, list[str]]:
    return _run(
        ["uv", "run", "pytest", "--cov=src/screen", "--cov-branch", f"--cov-report=json:{COVERAGE_JSON}"]
    )


def _check_ruff() -> tuple[bool, list[str]]:
    return _run(["uv", "run", "ruff", "check", "src", "tests"])


def _check_black() -> tuple[bool, list[str]]:
    return _run(["uv", "run", "black", "--check", "src", "tests"])


def _check_pyright() -> tuple[bool, list[str]]:
    return _run(["uv", "run", "pyright"])


def _check_coverage_tier() -> tuple[bool, list[str]]:
    if not COVERAGE_JSON.exists():
        return False, [
            f"coverage.json missing at {COVERAGE_JSON}",
            "pytest failed before writing it — re-run pytest alone to see the cause.",
        ]
    data = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
    violations: list[str] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        rel = _rel(py_file)
        if _is_exempt(rel):
            continue
        summary = data.get("files", {}).get(rel, {}).get("summary", {})
        if not summary:
            violations.append(f"{rel}: not present in coverage data")
            continue
        line_pct = summary.get("percent_covered")
        if line_pct is None:
            violations.append(f"{rel}: line coverage unknown in summary")
        elif line_pct < COVERAGE_TIER_PERCENT:
            violations.append(f"{rel}: line={line_pct:.1f}% < {COVERAGE_TIER_PERCENT}%")
        branch_pct = summary.get("percent_branches_covered")
        if branch_pct is None:
            violations.append(f"{rel}: branch coverage unknown in summary")
        elif branch_pct < BRANCH_TIER_PERCENT:
            violations.append(f"{rel}: branch={branch_pct:.1f}% < {BRANCH_TIER_PERCENT}%")
    return not violations, violations


def _check_no_type_ignore_markers() -> tuple[bool, list[str]]:
    offenders: list[str] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        rel = _rel(py_file)
        if _is_exempt(rel):
            continue
        for line_no, raw_line in enumerate(
            py_file.read_text("utf-8").splitlines(), start=1
        ):
            if any(p.search(raw_line) for p in _TYPE_IGNORE_PATTERNS):
                offenders.append(f"{rel}:{line_no}: {raw_line.strip()}")
    return not offenders, offenders


def _check_no_cover_pragmas_have_reasons() -> tuple[bool, list[str]]:
    """Every `# pragma: no cover` states why the line can't be tested, on the same line.

    At a 100% gate the pragma is the only way to leave a line uncovered, so an
    unexplained one is an untested line nobody decided about.
    """
    offenders: list[str] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        rel = _rel(py_file)
        if rel.startswith(GENERATED_CODE_DIR):
            continue
        for line_no, raw_line in enumerate(
            py_file.read_text("utf-8").splitlines(), start=1
        ):
            match = _NO_COVER_PRAGMA.search(raw_line)
            if match and not _NO_COVER_REASON.match(match.group("rest")):
                offenders.append(f"{rel}:{line_no}: {raw_line.strip()}")
    return not offenders, offenders


CheckFn = Callable[[], tuple[bool, list[str]]]


# (gate_name, what-it-checks, re-run-command-shown-on-failure)
CHECKS: list[tuple[str, str, str, CheckFn]] = [
    ("pytest", "test suite with branch coverage", "uv run pytest --cov=src/screen --cov-branch", _check_pytest),
    ("ruff", "lint (unused, complexity, imports)", "uv run ruff check src tests", _check_ruff),
    ("black", "formatting", "uv run black src tests", _check_black),
    ("pyright", "pyright strict", "uv run pyright", _check_pyright),
    ("coverage", "per-file coverage 100% line and branch", "uv run pytest --cov=src/screen --cov-branch --cov-report=json:coverage/coverage.json", _check_coverage_tier),
    ("no-type-ignore", "no `# type: ignore` / `# noqa` in src", "scripts/check.py", _check_no_type_ignore_markers),
    ("pragma-reason", "every `# pragma: no cover` in src gives a reason", "scripts/check.py", _check_no_cover_pragmas_have_reasons),
]


def main() -> int:
    print("Running discipline gates:\n")
    failed = False
    for name, label, rerun, check in CHECKS:
        ok, detail = check()
        status = "ok" if ok else "FAIL"
        print(f"  [{name}] {status} - {label}")
        if not ok:
            for line in detail:
                print(f"      {line}")
            print(f"      → to iterate: {rerun}")
        failed = failed or not ok
    print()
    if failed:
        print("Some gates failed.")
        return 1
    print("All gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
