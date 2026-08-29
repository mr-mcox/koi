"""Project discipline gate. Single entry point for all "is the repo ready
to commit?" checks.

When a gate fails, the message includes the standalone command to re-run
that one tool — that is the iteration loop the script can't replace.
"""

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "screen"
COVERAGE_JSON = REPO_ROOT / "coverage" / "coverage.json"

COVERAGE_TIER_PERCENT = 95
BRANCH_TIER_PERCENT = 95
EXEMPT_BUDGET = 1

GENERATED_CODE_DIR = "src/screen/baml_client/"

# Files that coverage.run omits — they never appear in coverage data, so
# the discipline gate can't compute their tier. Symmetric with
# pyproject.toml [tool.coverage.run] omit.
OMIT_FROM_COVERAGE: list[str] = [
    "src/screen/__main__.py",
    # Live BAML adapter: calls external LLM service, no unit test coverage by design.
    # Symmetric with pyproject.toml [tool.coverage.run] omit.
    "src/screen/extract/baml_extractor.py",
    "src/screen/digest/baml_digester.py",
]

EXEMPT_FILES: dict[str, str] = {
    "src/screen/browser.py": (
        "TavilyBrowser.fetch/extract live network paths are not exercised "
        "by unit tests; FakeTavily covers all protocol paths. Lands with slice 5."
    ),
}

_TYPE_IGNORE_PATTERNS = [
    re.compile(r"#\s*type:\s*ignore\b"),
    re.compile(r"#\s*pyright:\s*ignore\b"),
    re.compile(r"#\s*noqa\b"),
]


def _rel(py_file: Path) -> str:
    return str(py_file.relative_to(REPO_ROOT))


def _is_exempt(rel: str) -> bool:
    return (
        rel in EXEMPT_FILES
        or rel.startswith(GENERATED_CODE_DIR)
        or rel in OMIT_FROM_COVERAGE
    )


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


def _check_exempt_budget() -> tuple[bool, list[str]]:
    if len(EXEMPT_FILES) > EXEMPT_BUDGET:
        return False, [
            f"Exempt count {len(EXEMPT_FILES)} exceeds budget {EXEMPT_BUDGET}:"
        ] + [f"  {path}" for path in EXEMPT_FILES]
    return True, []


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


CheckFn = Callable[[], tuple[bool, list[str]]]


# (gate_name, what-it-checks, re-run-command-shown-on-failure)
CHECKS: list[tuple[str, str, str, CheckFn]] = [
    ("pytest", "test suite with branch coverage", "uv run pytest --cov=src/screen --cov-branch", _check_pytest),
    ("ruff", "lint (unused, complexity, imports)", "uv run ruff check src tests", _check_ruff),
    ("black", "formatting", "uv run black src tests", _check_black),
    ("pyright", "strict type checks", "uv run pyright", _check_pyright),
    ("coverage", "per-file coverage ≥95% line, ≥95% branch", "uv run pytest --cov=src/screen --cov-branch --cov-report=json:coverage/coverage.json", _check_coverage_tier),
    ("exempt-budget", "exempt-file count within configured budget", "scripts/check.py", _check_exempt_budget),
    ("no-type-ignore", "no `# type: ignore` / `# noqa` in src", "scripts/check.py", _check_no_type_ignore_markers),
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
