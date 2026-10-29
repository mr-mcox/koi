"""Acceptance tests for `.env` loading: the repo-root `.env` populates `os.environ` for
keys that aren't already set, and never clobbers a real environment variable (an
explicitly-exported key beats the file)."""

from pathlib import Path

from screen.env import load_env


def test_loads_keys_from_the_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SCREEN_TEST_PROBE=from_file\n", encoding="utf-8")
    environ: dict[str, str] = {}

    load_env(env_path=env_file, environ=environ)

    assert environ["SCREEN_TEST_PROBE"] == "from_file"


def test_an_already_set_variable_wins_over_the_file(tmp_path: Path) -> None:
    """An explicitly-exported key is the operator's deliberate override for this run —
    the file must not silently replace it."""
    env_file = tmp_path / ".env"
    env_file.write_text("SCREEN_TEST_PROBE=from_file\n", encoding="utf-8")
    environ = {"SCREEN_TEST_PROBE": "from_shell"}

    load_env(env_path=env_file, environ=environ)

    assert environ["SCREEN_TEST_PROBE"] == "from_shell"


def test_a_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    """Agent sessions and CI have no `.env`; absence is the normal case, not a failure."""
    environ: dict[str, str] = {}

    load_env(env_path=tmp_path / "does-not-exist", environ=environ)

    assert environ == {}
