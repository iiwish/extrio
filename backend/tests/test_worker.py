import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.credentials import CredentialCipher
from extrio.harvest import build_candidate
from extrio.runtime import RunResult
from extrio.store import DEFAULT_COLLECTOR_SCHEDULE, Store
from extrio.worker import Worker, classify_items, final_run_status


def accepted_item(*, run_id: str, title: str = "Notice A", observed_at: str = "2026-08-31 08:00") -> dict:
    return {
        "id": f"item_{run_id}",
        "collectorId": "collector_demo",
        "collectorName": "Demo",
        "sourceHost": "example.com",
        "listTitle": "Notice A",
        "title": title,
        "buyer": "Buyer",
        "region": "北京",
        "publishedAt": "2026-08-30",
        "budget": "100",
        "content": "Body",
        "sourceUrl": "https://example.com/detail/a",
        "decision": "accepted",
        "changeType": "new",
        "rejectionReason": None,
        "entityKey": "entity_a",
        "revision": 1,
        "observedAt": observed_at,
        "changeSummary": [],
        "observationHistory": [{"id": f"obs_{run_id}", "runId": run_id, "observedAt": observed_at, "outcome": "accepted"}],
        "lineage": {
            "sourceRevision": "source_revision_1",
            "collectionVersion": "v1",
            "ruleVersion": "rule_v1",
            "runId": run_id,
            "observationId": f"obs_{run_id}",
            "artifactId": f"artifact_{run_id}",
        },
    }


def test_item_classification_distinguishes_new_updated_and_unchanged() -> None:
    previous = accepted_item(run_id="previous")
    current = accepted_item(run_id="current", observed_at="2026-08-31 09:00")
    previous["collectorId"] = current["collectorId"] = "collector_demo"
    metrics = classify_items([current], [previous], "collector_demo")
    assert metrics == {"newItems": 0, "updatedItems": 0, "unchangedItems": 1}
    assert current["changeType"] == "unchanged"
    assert current["revision"] == 1
    assert len(current["observationHistory"]) == 2

    changed = accepted_item(run_id="changed", title="Notice A revised")
    changed["collectorId"] = "collector_demo"
    metrics = classify_items([changed], [previous], "collector_demo")
    assert metrics["updatedItems"] == 1
    assert changed["changeType"] == "updated"
    assert changed["revision"] == 2
    assert changed["changeSummary"] == [{"field": "title", "before": "Notice A", "after": "Notice A revised"}]

    fresh = accepted_item(run_id="fresh")
    fresh["collectorId"] = "collector_other"
    metrics = classify_items([fresh], [previous], "collector_other")
    assert metrics["newItems"] == 1
    assert fresh["changeType"] == "new"


def test_item_classification_uses_declared_fingerprint_fields() -> None:
    previous = accepted_item(run_id="previous")
    current = accepted_item(run_id="current")
    previous["extractedData"] = {"title": "A", "volatile": "first"}
    current["extractedData"] = {"title": "A", "volatile": "second"}

    metrics = classify_items([current], [previous], "collector_demo", ["title"])

    assert metrics["unchangedItems"] == 1
    assert current["changeSummary"] == []


@pytest.mark.parametrize(
    ("accepted", "rejected", "stop_reason", "expected"),
    [
        (0, 0, "checkpoint_reached", "succeeded"),
        (1, 0, "time_window_reached", "succeeded"),
        (1, 0, "max_pages", "partially_succeeded"),
        (0, 0, "max_pages", "failed"),
        (1, 0, "detail_fetch_incomplete", "partially_succeeded"),
        (1, 1, "next_link_exhausted", "partially_succeeded"),
    ],
)
def test_final_run_status_requires_a_normal_stop_reason(accepted: int, rejected: int, stop_reason: str, expected: str) -> None:
    assert final_run_status(accepted=accepted, rejected=rejected, stop_reason=stop_reason) == expected


def test_enqueue_run_deliveries_targets_only_accepted_new_updated_items_and_enabled_sinks(tmp_path: Path) -> None:
    store = Store(tmp_path / "enqueue.db")
    store.initialize()
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    enabled = store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/a", secret="s3cret")
    store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/b", secret="s3cret", enabled=False)
    fresh = accepted_item(run_id="run_fresh")
    fresh["collectorId"] = collector["id"]
    updated = accepted_item(run_id="run_updated")
    updated.update({"collectorId": collector["id"], "changeType": "updated", "revision": 2})
    rejected = accepted_item(run_id="run_rejected")
    rejected.update({"collectorId": collector["id"], "decision": "rejected", "changeType": None})
    unchanged = accepted_item(run_id="run_unchanged")
    unchanged.update({"collectorId": collector["id"], "changeType": "unchanged"})

    worker = Worker.__new__(Worker)
    worker.store = store

    assert worker.enqueue_run_deliveries(collector["id"], [fresh, updated, rejected, unchanged]) == 2
    deliveries = store.list_deliveries_for_collector(collector["id"])
    assert {delivery["itemEventId"] for delivery in deliveries} == {"item_run_fresh", "item_run_updated"}
    assert all(delivery["sinkId"] == enabled["id"] and delivery["status"] == "pending" for delivery in deliveries)
    assert worker.enqueue_run_deliveries("collector_without_sinks", [fresh]) == 0


@pytest.mark.asyncio
async def test_exploration_worker_finalizes_ai_run_without_marking_rule_published(tmp_path: Path) -> None:
    class FakeExplorer:
        async def explore(self, collector, _operation_id, progress, _ai_run_id=None, _attempt_id=None):
            await progress("fetching_list", 20, {"listPagesFetched": 1})
            candidate = build_candidate(
                collector,
                app_module.contracts,
                '<ul><li><a href="/detail/a">A</a></li></ul>',
                [("https://example.com/detail/a", '<h1 class="notice-title">A</h1>')],
            )
            return type(
                "ExplorationResult",
                (),
                {
                    "candidate": candidate,
                    "preview_items": [{"decision": "accepted"}, {"decision": "rejected"}],
                    "metrics": {"listPagesFetched": 1, "warningCount": 1},
                },
            )()

    store = Store(tmp_path / "ai-worker.db")
    store.initialize()
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"], "previousStatus": "draft", "aiRunId": "ai_run_worker"},
        collector_changes={"status": "exploring"},
        ai_run={
            "id": "ai_run_worker",
            "collectorId": collector["id"],
            "collectorName": collector["name"],
            "sourceUrl": collector["sourceUrl"],
            "kind": "rule_generation",
            "trigger": "initial_generation",
            "initiatedBy": "user_demo",
        },
    )
    job = store.claim_job(60)
    assert job is not None
    worker = Worker.__new__(Worker)
    worker.store = store
    worker.explorer = FakeExplorer()

    await worker.process(job)

    ai_run = store.get_ai_run("ai_run_worker")
    assert ai_run is not None
    assert ai_run["status"] == "succeeded"
    assert ai_run["resultStatus"] == "candidate_ready"
    assert ai_run["reviewStatus"] == "ready_review"
    assert ai_run["validationSummary"] == {"acceptedSamples": 1, "rejectedSamples": 1, "warningCount": 1}
    assert ai_run["candidateRuleDigest"]
    assert ai_run["attempts"][0]["status"] == "succeeded"
    assert store.get_collector(collector["id"])["status"] == "ready_review"


@pytest.mark.asyncio
async def test_worker_advances_checkpoint_only_after_successful_finalization(tmp_path: Path) -> None:
    class FakeRuntime:
        async def run(self, _collector, run, _progress):
            item = accepted_item(run_id=run["id"], observed_at=f"observed-{run['id']}")
            item["collectorId"] = run["collectorId"]
            item["collectorName"] = run["collectorName"]
            item["lineage"]["runId"] = run["id"]
            return RunResult(
                items=[item],
                metrics={
                    "listPagesFetched": 3,
                    "detailUrlsDiscovered": 1,
                    "detailPagesFetched": 1,
                    "recordsOutsideWindow": 4,
                    "duplicateDetailUrls": 0,
                    "newItems": 0,
                    "updatedItems": 0,
                    "unchangedItems": 0,
                    "warningCount": 0,
                },
                pagination_stop_reason="time_window_reached" if run["executionMode"] == "initial" else "checkpoint_reached",
                duration="0.1s",
                watermark_candidate="2026-08-30",
            )

    original = app_module.store
    app_module.store = Store(tmp_path / "worker.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
            cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
            sink = app_module.store.create_sink(
                collector["id"], cipher=cipher, url="https://hooks.example.com/extrio", secret="s3cret"
            )
            list_html = (
                '<ul class="notice-list"><li><a class="notice-title" href="/detail/a">Notice A</a>'
                '<time datetime="2026-08-30"></time></li></ul>'
            )
            detail_html = (
                '<h1 class="notice-title">Notice A</h1><div class="meta"><span data-field="buyer">Buyer</span>'
                '<time datetime="2026-08-30"></time></div><div class="notice-budget"><span class="amount">100</span></div>'
            )
            collector.update(
                status="ready_review",
                candidate=build_candidate(
                    collector,
                    app_module.contracts,
                    list_html,
                    [("https://example.com/detail/a", detail_html)],
                ),
            )
            app_module.store.save_collector(collector)
            decisions = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-worker-0001"},
                json={"reviewDecisions": decisions},
            )
            assert published.status_code == 200
            accepted = client.post(
                f"/api/v1/collectors/{collector['id']}/runs",
                headers={"Idempotency-Key": "run-worker-initial-0001"},
            )
            assert accepted.status_code == 202
            first_job = app_module.store.claim_job(60)
            assert first_job

            worker = Worker.__new__(Worker)
            worker.store = app_module.store
            worker.contracts = app_module.contracts
            worker.runtime = FakeRuntime()
            await worker.process(first_job)
            app_module.store.finish_job(first_job["id"])

            first_run = app_module.store.get_run(accepted.json()["resourceId"])
            assert first_run["status"] == "succeeded"
            assert first_run["newItems"] == 1
            assert first_run["checkpointAfter"]["watermark"] == "2026-08-30"
            assert app_module.store.get_checkpoint(collector["id"])["lastSuccessfulRunId"] == first_run["id"]

            deliveries = app_module.store.list_deliveries_for_collector(collector["id"])
            assert len(deliveries) == 1
            assert deliveries[0]["sinkId"] == sink["id"]
            assert deliveries[0]["itemEventId"] == first_run["items"][0]["id"]
            assert deliveries[0]["status"] == "pending"

            second = client.post(
                f"/api/v1/collectors/{collector['id']}/runs",
                headers={"Idempotency-Key": "run-worker-incremental-0001"},
            )
            assert second.status_code == 202
            second_run = app_module.store.get_run(second.json()["resourceId"])
            assert second_run["executionMode"] == "incremental"
            assert second_run["checkpointBefore"]["watermark"] == "2026-08-30"
            second_job = app_module.store.claim_job(60)
            assert second_job
            await worker.process(second_job)

            second_run = app_module.store.get_run(second.json()["resourceId"])
            assert second_run["status"] == "succeeded"
            assert second_run["unchangedItems"] == 1
            assert second_run["items"][0]["changeType"] == "unchanged"
            assert second_run["items"][0]["revision"] == 1
            assert len(second_run["items"][0]["observationHistory"]) == 2
            assert len(app_module.store.list_deliveries_for_collector(collector["id"])) == 1
    finally:
        app_module.store = original


def store_run(store: Store, run_id: str, collector_id: str, status: str) -> None:
    store.save_run(
        {
            "id": run_id,
            "collectorId": collector_id,
            "collectorName": "Demo",
            "status": status,
            "items": [],
        }
    )
    time.sleep(0.01)


def test_worker_pauses_schedule_after_three_consecutive_failed_runs(tmp_path: Path) -> None:
    store = Store(tmp_path / "pause.db")
    store.initialize()
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    enabled = store.save_schedule(collector["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    assert enabled["schedule"]["enabled"] is True
    for index in range(3):
        store_run(store, f"run_fail_{index}", collector["id"], "failed")

    worker = Worker.__new__(Worker)
    worker.store = store
    assert worker.maybe_pause_schedule_after_failures(collector["id"]) is True

    paused = store.get_collector(collector["id"])
    assert paused["schedule"]["enabled"] is False
    assert paused["schedule"]["cronExpression"] == enabled["schedule"]["cronExpression"]
    assert paused["schedule"]["timezone"] == enabled["schedule"]["timezone"]
    assert paused["schedule"]["overlapPolicy"] == enabled["schedule"]["overlapPolicy"]

    revision_before = paused["schedule"]["revision"]
    assert worker.maybe_pause_schedule_after_failures(collector["id"]) is False
    still_paused = store.get_collector(collector["id"])
    assert still_paused["schedule"]["enabled"] is False
    assert still_paused["schedule"]["revision"] == revision_before


def test_worker_keeps_schedule_enabled_when_failures_are_interrupted_by_success(tmp_path: Path) -> None:
    store = Store(tmp_path / "intermittent.db")
    store.initialize()
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    store.save_schedule(collector["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    for index, status in enumerate(("failed", "succeeded", "failed")):
        store_run(store, f"run_{status}_{index}", collector["id"], status)

    worker = Worker.__new__(Worker)
    worker.store = store
    assert worker.maybe_pause_schedule_after_failures(collector["id"]) is False
    assert store.get_collector(collector["id"])["schedule"]["enabled"] is True


def test_worker_keeps_schedule_enabled_with_fewer_than_three_failures(tmp_path: Path) -> None:
    store = Store(tmp_path / "short.db")
    store.initialize()
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    store.save_schedule(collector["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    for index in range(2):
        store_run(store, f"run_fail_{index}", collector["id"], "failed")

    worker = Worker.__new__(Worker)
    worker.store = store
    assert worker.maybe_pause_schedule_after_failures(collector["id"]) is False
    assert store.get_collector(collector["id"])["schedule"]["enabled"] is True


@pytest.mark.asyncio
async def test_run_finalization_pauses_schedule_after_three_failed_runs(tmp_path: Path) -> None:
    class FailingRuntime:
        async def run(self, _collector, _run, _progress):
            return RunResult(
                items=[],
                metrics={
                    "listPagesFetched": 0,
                    "detailUrlsDiscovered": 0,
                    "detailPagesFetched": 0,
                    "recordsOutsideWindow": 0,
                    "duplicateDetailUrls": 0,
                    "newItems": 0,
                    "updatedItems": 0,
                    "unchangedItems": 0,
                    "warningCount": 0,
                },
                pagination_stop_reason="max_pages",
                duration="0.1s",
                watermark_candidate=None,
            )

    original = app_module.store
    app_module.store = Store(tmp_path / "worker-pause.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
            store = app_module.store
            schedule = store.save_schedule(collector["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
            assert schedule["schedule"]["enabled"] is True
            list_html = (
                '<ul class="notice-list"><li><a class="notice-title" href="/detail/a">Notice A</a>'
                '<time datetime="2026-08-30"></time></li></ul>'
            )
            detail_html = (
                '<h1 class="notice-title">Notice A</h1><div class="meta"><span data-field="buyer">Buyer</span>'
                '<time datetime="2026-08-30"></time></div><div class="notice-budget"><span class="amount">100</span></div>'
            )
            collector.update(
                status="ready_review",
                candidate=build_candidate(
                    collector,
                    app_module.contracts,
                    list_html,
                    [("https://example.com/detail/a", detail_html)],
                ),
            )
            store.save_collector(collector)
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-pause-0001"},
                json={"reviewDecisions": {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}},
            )
            assert published.status_code == 200, published.json()

            worker = Worker.__new__(Worker)
            worker.store = store
            worker.contracts = app_module.contracts
            worker.runtime = FailingRuntime()
            for index in range(3):
                accepted = client.post(
                    f"/api/v1/collectors/{collector['id']}/runs",
                    headers={"Idempotency-Key": f"run-pause-{index:04d}-key"},
                )
                assert accepted.status_code == 202, accepted.json()
                job = store.claim_job(60)
                assert job is not None
                await worker.process(job)
                store.finish_job(job["id"])

            assert store.recent_run_statuses(collector["id"], 3) == ["failed", "failed", "failed"]
            paused = store.get_collector(collector["id"])
            assert paused["schedule"]["enabled"] is False
            assert paused["schedule"]["cronExpression"] == DEFAULT_COLLECTOR_SCHEDULE["cronExpression"]
    finally:
        app_module.store = original
