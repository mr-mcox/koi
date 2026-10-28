"""The dependency direction between `screen`'s packages, enforced.

docs/architecture/README.md names one of these as a girder (`research/` never
imports `intake/`); the rest are the layering that keeps it true — the trace
substrate below both, and the pool ranking below the web layer so research can
rank without importing a route module.

A layer may import its own layer and anything below it, never above. Adding a
module to `screen/` without placing it here fails the test rather than silently
escaping the rule.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "screen"

# Top-level names under `screen/`, lowest layer first. Generated BAML output and
# the composition root are the two ends: nothing may import `wiring`, and
# `baml_client` imports nothing of ours.
LAYERS: list[set[str]] = [
    {"baml_client", "types", "paths", "env", "browser", "store"},
    {"research_trace", "score", "verdict", "extract", "digest"},
    {"pool", "recalibration", "recalibration_run"},
    {"research", "intake"},
    {"api", "web"},
    {"wiring"},
]

# Same-layer pairs that are still forbidden. `intake/` drives a research pass, so
# it may import `research/`; the reverse would make the trace substrate's split
# pointless and put file-shaped intake concerns inside the dispatch loop.
FORBIDDEN_PAIRS: set[tuple[str, str]] = {("research", "intake")}

# The ASGI entrypoint is below `wiring` only by filename: it exists to call the
# composition root, so it is the one module allowed to import upward.
ENTRYPOINTS = {"screen/api/main.py"}

_LAYER_OF: dict[str, int] = {name: i for i, layer in enumerate(LAYERS) for name in layer}


def _top_level(module: Path) -> str:
    """The `screen.<name>` a source file belongs to, package or single module."""
    return module.relative_to(SRC_ROOT).parts[0].removesuffix(".py")


def _imported_screen_packages(source: str) -> set[str]:
    """Top-level `screen.<name>` packages imported by one module's source."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] == "screen" and len(parts) > 1:
                imported.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "screen" and len(parts) > 1:
                    imported.add(parts[1])
    return imported


def _source_files() -> list[Path]:
    return sorted(
        p
        for p in SRC_ROOT.rglob("*.py")
        if p.name != "__init__.py" and str(p.relative_to(SRC_ROOT.parent)) not in ENTRYPOINTS
    )


def test_every_top_level_module_is_placed_in_a_layer() -> None:
    """An unplaced module would be exempt from every rule below."""
    placed = set(_LAYER_OF)
    actual = {_top_level(p) for p in _source_files()}
    assert actual <= placed, f"unlayered modules: {sorted(actual - placed)}"


def test_imports_never_point_up_a_layer() -> None:
    violations: list[str] = []
    for path in _source_files():
        importer = _top_level(path)
        for imported in _imported_screen_packages(path.read_text(encoding="utf-8")):
            if _LAYER_OF.get(imported, -1) > _LAYER_OF[importer]:
                violations.append(f"{path.relative_to(SRC_ROOT.parent)} imports screen.{imported}")
    assert not violations, "upward imports: " + "; ".join(violations)


def test_forbidden_same_layer_imports_are_absent() -> None:
    violations: list[str] = []
    for path in _source_files():
        importer = _top_level(path)
        for imported in _imported_screen_packages(path.read_text(encoding="utf-8")):
            if (importer, imported) in FORBIDDEN_PAIRS:
                violations.append(f"{path.relative_to(SRC_ROOT.parent)} imports screen.{imported}")
    assert not violations, "forbidden imports: " + "; ".join(violations)
