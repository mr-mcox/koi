"""Migration runner: applies numbered .sql files once each, in order."""

import sqlite3
from pathlib import Path

import pytest

from screen.store.migrate import apply_migrations


def _write(migrations_dir: Path, name: str, sql: str) -> None:
    (migrations_dir / name).write_text(sql, encoding="utf-8")


def test_applies_migrations_in_numeric_order(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write(migrations_dir, "0001_create_widgets.sql", "CREATE TABLE widgets (id TEXT PRIMARY KEY);")
    _write(
        migrations_dir,
        "0002_add_widget_name.sql",
        "ALTER TABLE widgets ADD COLUMN name TEXT;",
    )
    conn = sqlite3.connect(":memory:")

    apply_migrations(conn, migrations_dir)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(widgets)")}
    assert cols == {"id", "name"}


def test_does_not_reapply_already_applied_migrations(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write(migrations_dir, "0001_create_widgets.sql", "CREATE TABLE widgets (id TEXT PRIMARY KEY);")
    conn = sqlite3.connect(":memory:")

    apply_migrations(conn, migrations_dir)
    # A second call must be a no-op, not a "table already exists" error.
    apply_migrations(conn, migrations_dir)

    applied = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    assert applied == [("0001_create_widgets.sql",)]


def test_new_migration_added_later_is_applied_on_next_run(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write(migrations_dir, "0001_create_widgets.sql", "CREATE TABLE widgets (id TEXT PRIMARY KEY);")
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations_dir)

    _write(migrations_dir, "0002_create_gadgets.sql", "CREATE TABLE gadgets (id TEXT PRIMARY KEY);")
    apply_migrations(conn, migrations_dir)

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"widgets", "gadgets"} <= tables


def test_a_failing_migration_raises_and_is_not_recorded_as_applied(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write(migrations_dir, "0001_broken.sql", "NOT VALID SQL;")
    conn = sqlite3.connect(":memory:")

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn, migrations_dir)

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert (
        "schema_migrations" not in tables
        or not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = '0001_broken.sql'"
        ).fetchall()
    )
