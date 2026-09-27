import pytest
from fastapi.testclient import TestClient
from test_release_upgrade import databases as databases

import extrio.app as app_module
from extrio.store import Store
from extrio.store_dialect import DialectConnection


def test_current_runtime_never_reads_history_payloads(tmp_path, monkeypatch, databases):
    store = Store(tmp_path / "current.db", database_url=databases[0])
    store.initialize(migrate=True)
    store.create_collector("Current", "Collect", "https://example.com/list", "example.com")
    execute = DialectConnection.execute

    def guard(connection, query, params=()):
        lowered = query.lower()
        historical = any(f"from {table}" in lowered for table in ("items", "runs", "operations", "ai_runs"))
        if lowered.lstrip().startswith("select") and historical:
            pytest.fail(f"runtime startup read historical records: {query}")
        return execute(connection, query, params)

    monkeypatch.setattr(DialectConnection, "execute", guard)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"seed_demo": False}))
    store.initialize(migrate=False)
    store.initialize(migrate=True)
    with TestClient(app_module.app):
        pass


def test_completed_backfill_does_not_repeat(tmp_path, monkeypatch, databases):
    store = Store(tmp_path / "once.db", database_url=databases[0])
    store.initialize(migrate=True)
    monkeypatch.setattr(store, "_backfill_collections", lambda: pytest.fail("completed collection backfill repeated"))
    monkeypatch.setattr(store, "_backfill_ai_runs", lambda *_: pytest.fail("completed AI backfill repeated"))
    store.initialize(migrate=True)
    store.initialize(migrate=False)


def test_new_source_defaults_commit_with_source(tmp_path, monkeypatch, databases):
    store = Store(tmp_path / "source.db", database_url=databases[0])
    store.initialize(migrate=True)

    def fail_schedule(*args, **kwargs):
        raise RuntimeError("schedule write failed")

    with monkeypatch.context() as patch:
        patch.setattr(store, "ensure_schedule", fail_schedule)
        with pytest.raises(RuntimeError, match="schedule write failed"):
            store.create_collector("Atomic", "Collect", "https://example.com/list", "example.com")
    assert store.list_collectors() == []
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS count FROM collection_policies").fetchone()["count"] == 0
    source = store.create_collector("Atomic", "Collect", "https://example.com/list", "example.com")
    assert source["collectionPolicy"]["id"] == source["activeCollectionPolicyId"]
    assert source["schedule"]["enabled"] is False


def test_backfill_is_batched_restartable_and_preserves_existing_values(tmp_path, monkeypatch, databases):
    from extrio import store_backfills

    store = Store(tmp_path / "legacy.db", database_url=databases[0])
    store.initialize(migrate=True)
    source = store.create_collector("Legacy", "Collect", "https://example.com/list", "example.com")
    store.save_run({"id": "run_legacy", "collectorId": source["id"], "status": "succeeded", "items": [], "newItems": 7})
    items = [{"id": f"item_{number}", "lineage": {"runId": "run_legacy"}, "extractedData": {"title": str(number)}} for number in range(5)]
    items[0]["changeType"] = "updated"
    store.save_items("run_legacy", items)
    with store.connect() as connection:
        before = {row["id"]: row["created_at"] for row in connection.execute("SELECT id, created_at FROM items").fetchall()}
        connection.execute("DELETE FROM data_migrations")
    monkeypatch.setattr(store_backfills, "BATCH_SIZE", 2)
    execute = DialectConnection.execute
    item_updates = []

    def interrupt(connection, query, params=()):
        if query.startswith("UPDATE items SET data="):
            item_updates.append(params[-1])
            if len(item_updates) == 3:
                raise RuntimeError("interrupted backfill")
        return execute(connection, query, params)

    with monkeypatch.context() as patch:
        patch.setattr(DialectConnection, "execute", interrupt)
        with pytest.raises(RuntimeError, match="interrupted backfill"):
            store.initialize(migrate=True)
    assert item_updates == ["item_1", "item_2", "item_3"]
    with store.connect() as connection:
        assert connection.execute("SELECT * FROM data_migrations").fetchall() == []
        values = {row["id"]: store._decode(row) for row in connection.execute("SELECT id, data FROM items").fetchall()}
        assert values["item_1"]["changeType"] is None
        assert "changeType" not in values["item_2"]
    with pytest.raises(RuntimeError, match="data migrations are incomplete"):
        store.initialize(migrate=False)
    batch_sizes = []
    original_batches = store_backfills.record_batches

    def observed_batches(*args, **kwargs):
        for rows in original_batches(*args, **kwargs):
            batch_sizes.append(len(rows))
            yield rows

    monkeypatch.setattr(store_backfills, "record_batches", observed_batches)
    store.initialize(migrate=True)
    assert batch_sizes and max(batch_sizes) <= 2
    assert store.get_run("run_legacy")["newItems"] == 7
    with store.connect() as connection:
        rows = connection.execute("SELECT id, data, created_at FROM items ORDER BY id").fetchall()
        assert {row["id"]: row["created_at"] for row in rows} == before
        for row, original in zip(rows, items, strict=True):
            assert store._decode(row) == {"changeType": None, **original}
        assert len(connection.execute("SELECT * FROM data_migrations").fetchall()) == 1
