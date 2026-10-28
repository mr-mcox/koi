"""screen.paths.data_dir() is the single source of the SCREEN_DATA_DIR seam,
shared by the CLI and the API."""

from pathlib import Path

from screen.paths import data_dir


def test_data_dir_defaults_to_data() -> None:
    assert data_dir({}) == Path("data").resolve()


def test_data_dir_honors_env_var(tmp_path: Path) -> None:
    assert data_dir({"SCREEN_DATA_DIR": str(tmp_path)}) == tmp_path.resolve()
