import pytest
from test_collection_versions import client as client
from test_job_recovery import make_worker, prepared_run, result_for

import extrio.app as app_module


def test_latest_entity_window_has_a_covering_order_index(client):
    store = app_module.store
    with store.connect() as connection:
        if store.dialect.name == "sqlite":
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_items_entity_latest'").fetchall()
        else:
            rows = connection.execute("SELECT indexname FROM pg_indexes WHERE indexname='idx_items_entity_latest'").fetchall()
    assert rows, "latest-entity ranking must not sort complete historical JSON payloads"


@pytest.mark.asyncio
async def test_worker_does_not_load_unrelated_item_history(client, monkeypatch):
    store, source, operation, job = prepared_run(client)
    def forbidden_scan():
        raise AssertionError("Worker must not scan every item in the instance")
    monkeypatch.setattr(store, "list_items", forbidden_scan)
    class Runtime:
        async def run(self, source, run, progress):
            return result_for(source, run)
    await make_worker(store, Runtime()).process(job)
    assert store.get_run(operation["resourceId"])["newItems"] == 1


@pytest.mark.parametrize("value", ["=1+1", "+SUM(1,2)", "-1+1", "@SUM(1,2)", "\t=1+1", "\r=1+1", "  =1+1"])
def test_csv_neutralizes_untrusted_spreadsheet_formulas(value):
    row = app_module.export_csv_row({"extractedData": {"title": value}}, ["title"])
    assert row[-1] == "'" + value
