import asyncio
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from test_api import ready_review_collector
from test_release_upgrade import databases as databases

import extrio.app as app_module
from extrio.store import DEFAULT_COLLECTOR_SCHEDULE, Store


@pytest.fixture
def scheduled_store(tmp_path, monkeypatch, databases):
    store = Store(tmp_path / "schedule.db", database_url=databases[0])
    store.initialize()
    monkeypatch.setattr(app_module, "store", store)
    source = ready_review_collector(store)
    app_module.persist_published_rule(
        source, rule_version_id="rule_schedule_v1",
        review_decisions={"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"},
        request_id="schedule-test", actor_id="schedule-test",
    )
    store.save_schedule(source["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})

    async def end_poll(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", end_poll)
    return store, source["id"]


def poll_once():
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_module.schedule_dispatch_loop())


def claim(store):
    return store.claim_due_schedules(datetime.now(UTC) + timedelta(days=1))[0]


def occurrence_state(store, key):
    with store.connect() as connection:
        return dict(connection.execute("SELECT status, run_id FROM schedule_occurrences WHERE occurrence_key=?", (key,)).fetchone())


def test_claimed_schedule_survives_restart(scheduled_store, monkeypatch):
    store, _ = scheduled_store
    occurrence = claim(store)
    restarted = Store(store.path, database_url=store.database_url or "")
    restarted.initialize(migrate=False)
    monkeypatch.setattr(app_module, "store", restarted)
    poll_once()
    assert len(restarted.list_runs()) == 1
    assert occurrence_state(restarted, occurrence["occurrenceKey"])["status"] == "dispatched"
    poll_once()
    assert len(restarted.list_runs()) == 1


def test_enqueue_and_dispatch_receipt_roll_back_together(scheduled_store, monkeypatch):
    store, source_id = scheduled_store
    occurrence = claim(store)
    finish = store.finish_schedule_occurrence

    def crash(*args, **kwargs):
        finish(*args, **kwargs)
        raise RuntimeError("crash before dispatch commit")

    with monkeypatch.context() as patch:
        patch.setattr(store, "finish_schedule_occurrence", crash)
        poll_once()
    assert store.list_runs() == []
    assert store.list_operations() == []
    assert store.get_collector(source_id)["activeOperationId"] is None
    assert occurrence_state(store, occurrence["occurrenceKey"]) == {"status": "claimed", "run_id": None}
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"] == 0
    poll_once()
    assert len(store.list_runs()) == 1
    assert occurrence_state(store, occurrence["occurrenceKey"])["status"] == "dispatched"


def test_concurrent_dispatchers_create_one_job(scheduled_store, monkeypatch):
    store, _ = scheduled_store
    occurrence = claim(store)
    pending = store.pending_schedule_occurrences
    barrier = threading.Barrier(2)

    def concurrent_pending():
        rows = pending()
        assert len(rows) == 1
        barrier.wait(timeout=10)
        return rows

    monkeypatch.setattr(store, "pending_schedule_occurrences", concurrent_pending)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: poll_once(), range(2)))
    assert len(store.list_runs()) == 1
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"] == 1
    assert occurrence_state(store, occurrence["occurrenceKey"])["status"] == "dispatched"


def test_process_exit_during_dispatch_leaves_no_partial_job(scheduled_store):
    store, _ = scheduled_store
    occurrence = claim(store)
    code = """
import os
import extrio.app as app
app.store.initialize(migrate=False)
finish = app.store.finish_schedule_occurrence
def exit_before_commit(*args, **kwargs):
    finish(*args, **kwargs)
    os._exit(17)
app.store.finish_schedule_occurrence = exit_before_commit
app.dispatch_schedule_occurrence(app.store.pending_schedule_occurrences()[0])
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "EXTRIO_DATABASE_PATH": str(store.path), "EXTRIO_DATABASE_URL": store.database_url or ""},
        capture_output=True, timeout=20,
    )
    assert result.returncode == 17, result.stderr.decode()
    assert store.list_runs() == []
    assert occurrence_state(store, occurrence["occurrenceKey"])["status"] == "claimed"
    poll_once()
    assert len(store.list_runs()) == 1


def test_blocked_pending_occurrence_is_explicitly_skipped(scheduled_store):
    store, source_id = scheduled_store
    occurrence = claim(store)
    source = store.get_collector(source_id)
    store.save_collector({**source, "status": "draft", "activeRuleVersion": None})
    poll_once()
    assert occurrence_state(store, occurrence["occurrenceKey"]) == {"status": "skipped", "run_id": None}
    with store.connect() as connection:
        assert connection.execute("SELECT reason FROM schedule_occurrences").fetchone()["reason"] == "RULE_NOT_PUBLISHED"


@pytest.mark.parametrize("enabled,reason", [(False, "SCHEDULE_DISABLED"), (True, "SCHEDULE_CHANGED")])
def test_recovery_does_not_revive_paused_or_revised_schedule(scheduled_store, enabled, reason):
    store, source_id = scheduled_store
    occurrence = claim(store)
    store.save_schedule(source_id, {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": enabled, "cronExpression": "0 9 * * *"})
    poll_once()
    assert store.list_runs() == []
    assert occurrence_state(store, occurrence["occurrenceKey"])["status"] == "skipped"
    with store.connect() as connection:
        assert connection.execute("SELECT reason FROM schedule_occurrences").fetchone()["reason"] == reason
