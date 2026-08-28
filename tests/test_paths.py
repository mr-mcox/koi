"""screen.paths.data_dir() is the single source of the SCREEN_DATA_DIR seam,
shared by the CLI and the API — previously duplicated in both.
"""

from pathlib import Path

from screen.paths import data_dir


def test_data_dir_defaults_to_data(monkeypatch):
    monkeypatch.delenv("SCREEN_DATA_DIR", raising=False)
    assert data_dir() == Path("data").resolve()


def test_data_dir_honors_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("SCREEN_DATA_DIR", str(tmp_path))
    assert data_dir() == tmp_path.resolve()
