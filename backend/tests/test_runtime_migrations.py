import sqlite3
from pathlib import Path

import pytest

import extrio.cli as cli
from extrio.config import Settings
from extrio.store import Store
from extrio.store_dialect import SQLiteDialect


@pytest.mark.parametrize("failure", ["foreign_key", "sql"])
def test_failed_sqlite_migration_rolls_back_data_schema_and_marker(tmp_path, failure):
    dialect = SQLiteDialect()
    with dialect.connect(None, tmp_path / "rollback.db") as connection:
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        connection.execute("CREATE TABLE schema_migrations(id TEXT PRIMARY KEY)")
        script = "CREATE TABLE added(id INTEGER); INSERT INTO child VALUES(1, 999); INSERT INTO schema_migrations VALUES('broken');"
        if failure == "sql":
            script += " INSERT INTO missing_table VALUES(1);"
        with pytest.raises(RuntimeError if failure == "foreign_key" else sqlite3.OperationalError):
            dialect.run_script(connection, script)
        assert connection.execute("SELECT * FROM child").fetchall() == []
        assert connection.execute("SELECT * FROM schema_migrations").fetchall() == []
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='added'").fetchall() == []
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not connection.raw.in_transaction


def test_sqlite_migration_can_rebuild_referenced_table(tmp_path):
    dialect = SQLiteDialect()
    with dialect.connect(None, tmp_path / "rebuild.db") as connection:
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        connection.execute("INSERT INTO parent VALUES(1)")
        connection.execute("INSERT INTO child VALUES(1)")
        dialect.run_script(connection, "CREATE TABLE replacement(id INTEGER PRIMARY KEY); INSERT INTO replacement SELECT * FROM parent; "
                           "DROP TABLE parent; ALTER TABLE replacement RENAME TO parent;")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT parent_id FROM child").fetchone()[0] == 1


def test_runtime_requires_migrated_schema(tmp_path):
    store = Store(tmp_path / "test.db", database_url="")
    with pytest.raises(RuntimeError, match="migration job"):
        store.initialize(migrate=False)
    store.initialize(migrate=True)
    store.initialize(migrate=False)
    with store.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE id='010_source_history_ownership'")
    with pytest.raises(RuntimeError, match="does not match"):
        store.initialize(migrate=False)


def test_runtime_does_not_execute_ddl(tmp_path, monkeypatch):
    store = Store(tmp_path / "test.db", database_url="")
    store.initialize(migrate=True)
    monkeypatch.setattr(store, "_run_migrations", lambda _: pytest.fail("runtime must not migrate"))
    store.initialize(migrate=False)


def test_explicit_migration_command_initializes_runtime_schema(tmp_path, monkeypatch):
    settings = Settings(
        database_path=tmp_path / "explicit.db",
        database_auto_migrate=False,
        contracts_path=Path(__file__).resolve().parents[2] / "docs" / "contracts",
        _env_file=None,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    cli.run_migrate()
    store = Store(settings.database_path)
    store.initialize(migrate=False)


def test_migration_command_refuses_running_instance(tmp_path, monkeypatch):
    from extrio.instance_guard import instance_lock

    settings = Settings(database_path=tmp_path / "live.db", artifact_path=tmp_path / "artifacts", _env_file=None)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    with instance_lock(settings.artifact_path), pytest.raises(RuntimeError, match="instance is running"):
        cli.run_migrate()
    assert not settings.database_path.exists()
