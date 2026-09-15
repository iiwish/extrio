import pytest

from extrio.store import Store


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
