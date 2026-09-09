from datetime import UTC, datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from test_api_output import output_client, output_item, seed_items


def seed_overview(store):
    collector = store.create_collector("Overview", "Collect", "https://example.com/list", "example.com")
    with store.transaction() as connection:
        for index in range(205):
            run = {"id": f"overview_{index}", "collectorId": collector["id"], "status": "succeeded", "acceptedCount": 2, "rejectedCount": 1}
            store.save_run(run, connection)
        connection.execute("UPDATE runs SET created_at=?", ("2026-09-06T00:00:00Z",))
    return collector


def test_overview_aggregates_all_runs_and_excludes_inflight_from_success_rate(tmp_path):
    with output_client(tmp_path) as (store, client):
        collector = seed_overview(store)
        for status in ["partially_succeeded", "failed", "cancelled", "timed_out", "queued", "running", "finalizing"]:
            store.save_run({"id": status, "collectorId": collector["id"], "status": status, "acceptedCount": 0, "rejectedCount": 0})
        with store.transaction() as connection:
            connection.execute("UPDATE runs SET created_at=?", ("2026-09-06T00:00:00Z",))
        result = store.overview(timezone="Asia/Shanghai", now=datetime(2026, 9, 6, 12, tzinfo=UTC))
        assert result["today"]["runs"] == 212
        assert result["today"]["accepted"] == 410
        assert result["today"]["rejected"] == 205
        assert result["week"]["successful"] == 205
        assert result["week"]["partial"] == 1
        assert result["week"]["failed"] == 3
        assert result["week"]["active"] == 3
        assert result["week"]["completed"] == 209
        assert len(result["trends"]["day"]) == 14
        assert len(result["trends"]["week"]) == len(result["trends"]["month"]) == 12
        assert sum(bucket["runs"] for bucket in result["trends"]["day"]) == 212
        response = client.get("/api/v1/overview?timezone=Asia%2FShanghai")
        assert response.status_code == 200
        contract = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/contracts/openapi.yaml").read_text())
        schema = {"$ref": "#/components/schemas/Overview", "components": contract["components"]}
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(response.json())
        assert client.get("/api/v1/overview?timezone=Not_A_Zone").status_code == 422


def test_overview_local_midnight_monday_and_year_boundary(tmp_path):
    with output_client(tmp_path) as (store, _):
        collector = store.create_collector("Boundary", "Collect", "https://example.com/list", "example.com")
        for key, at in [("before", "2025-12-31T15:59:59Z"), ("start", "2025-12-31T16:00:00Z"), ("end", "2026-01-01T16:00:00Z")]:
            store.save_run({"id": key, "collectorId": collector["id"], "status": "succeeded", "acceptedCount": 1})
            with store.transaction() as connection:
                connection.execute("UPDATE runs SET created_at=? WHERE id=?", (at, key))
        result = store.overview(timezone="Asia/Shanghai", now=datetime(2026, 1, 1, 12, tzinfo=UTC))
        assert result["today"]["runs"] == 1
        assert result["today"]["start"] == "2025-12-31T16:00:00Z"
        assert result["week"]["start"] == "2025-12-28T16:00:00Z"
        assert result["trends"]["month"][0]["labelDate"] == "2025-02-01"


def test_overview_latest_entities_before_period_filter_and_no_list_cap(tmp_path):
    with output_client(tmp_path) as (store, _):
        collector = store.create_collector("Entities", "Collect", "https://example.com/list", "example.com")
        rows = [output_item(f"item_{i}", collector["id"], "old", "2026-09-01 10:00", str(i)) for i in range(205)]
        seed_items(store, collector["id"], "old", rows)
        rejected_item = output_item("latest", collector["id"], "new", "2026-09-02 10:00", "0", decision="rejected")
        seed_items(store, collector["id"], "new", [rejected_item])
        with store.transaction() as connection:
            connection.execute("UPDATE items SET created_at=?", ("2026-09-01T00:00:00Z",))
            connection.execute("UPDATE items SET created_at=? WHERE id=?", ("2026-10-01T00:00:00Z", "latest"))
        result = store.overview(timezone="UTC", now=datetime(2026, 9, 15, tzinfo=UTC))
        assert result["monthEntities"] == {"total": 204, "accepted": 204, "rejected": 0}
        assert result["collectors"] == {"total": len(store.list_collectors()), "published": 0}


def test_overview_dst_buckets_are_calendar_days(tmp_path):
    with output_client(tmp_path) as (store, _):
        result = store.overview(timezone="America/New_York", now=datetime(2026, 3, 8, 12, tzinfo=UTC))
        assert result["today"]["start"] == "2026-03-08T05:00:00Z"
        assert result["today"]["end"] == "2026-03-09T04:00:00Z"
        assert result["today"]["completed"] == 0
