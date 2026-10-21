"""Signed API -> real HTTP runtime -> transactional incremental finalization."""

import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_api_output import output_item, seed_items
from test_collection_versions import client as client

import extrio.app as app_module
from extrio.config import Settings
from extrio.credentials import CredentialCipher
from extrio.harvest import build_candidate
from extrio.runtime import CrawleeRuntime
from extrio.store import Store
from extrio.worker import Worker


def test_same_minute_records_use_persistence_order_before_random_ids(client):
    store = app_module.store
    collector = store.create_collector("Same-minute fixture", "Collect", "https://example.com/list", "example.com")
    for item_id, run_id, value in [("zz_old", "run_old", "old"), ("aa_new", "run_new", "new")]:
        item = output_item(item_id, collector["id"], run_id, "2026-10-19 10:00", "same-entity")
        item["content"] = value
        seed_items(store, collector["id"], run_id, [item])
    latest = store.latest_accepted_items(collector["id"], {"same-entity"})
    assert [i["id"] for i in latest] == ["aa_new"]
    current = client.get("/api/v1/items", params={"view": "entities", "collectorId": collector["id"]}).json()
    assert [i["id"] for i in current["items"]] == ["aa_new"]


@pytest.mark.asyncio
@pytest.mark.parametrize('coverage_mode', ['accepted_only', 'observed'])
async def test_signed_incremental_http_pipeline_detects_changes_late_items_and_deduplicates(tmp_path, monkeypatch, coverage_mode):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    yesterday = today - timedelta(days=1)
    old = today - timedelta(days=90)
    state = {"phase": 0, "requests": []}

    def list_html(page):
        if page == 1:
            rows = [("A", today)]
            if state["phase"]:
                rows += [("C", today), ("A", today)]
            rows += [("B", yesterday)]
            if state["phase"]:
                rows += [("late", yesterday)]
        else:
            rows = [(f"old-{page}", old)]
        items = "".join(
            f'<li><a class="notice-title" href="/detail/{code}">{code}</a>'
            f'<time datetime="{published}T00:00:00+08:00"></time></li>'
            for code, published in rows
        )
        # An old-window stop, rather than an exhausted pager, must finish page 3.
        return f'<ul class="notice-list">{items}</ul><a class="pagination-next" href="/list?page={page + 1}">Next</a>'

    def detail_html(code):
        published = yesterday if code in {"B", "late"} else today
        budget = "200" if state["phase"] and code == "A" else "100"
        return (
            f'<h1 class="notice-title">{code}</h1><div class="meta"><span data-field="buyer">Buyer</span>'
            f'<time datetime="{published}T00:00:00+08:00"></time></div>'
            f'<div class="notice-budget"><span class="amount">{budget}</span></div>'
        )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            state["requests"].append(self.path)
            parts = urlsplit(self.path)
            if parts.path == "/robots.txt":
                payload = b"User-agent: *\nAllow: /\n"
            elif parts.path == "/list":
                payload = list_html(int(parse_qs(parts.query).get("page", ["1"])[0])).encode()
            else:
                payload = detail_html(parts.path.rsplit("/", 1)[-1]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    entry = f"http://127.0.0.1:{server.server_port}/list"
    store = Store(tmp_path / "incremental.db")
    store.initialize()
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr("extrio.runtime.get_settings", lambda: Settings(allow_http_localhost=True))
    try:
        with TestClient(app_module.app) as client:
            collector = store.create_collector("Incremental fixture", "Collect notices", entry, "127.0.0.1")
            collector.update(status="ready_review", candidate=build_candidate(
                collector, app_module.contracts, list_html(1), [(entry.replace("/list", "/detail/A"), detail_html("A"))],
            ))
            store.save_collector(collector)
            policy = client.post(
                f"/api/v1/collectors/{collector['id']}/collection-policy",
                headers={"Idempotency-Key": "incremental-e2e-policy"},
                json={"mode": "rolling_incremental", "initialWindowDays": 30, "lookbackDays": 3,
                      "consecutiveOlderPages": 2, "maxPages": 3, "maxItems": 50, "timezone": "Asia/Shanghai",
                      "checkpointMode": coverage_mode},
            )
            assert policy.status_code == 200, policy.text
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "incremental-e2e-publish"},
                json={"reviewDecisions": {"title": "approved", "buyer": "approved", "publishedAt": "approved",
                                          "budget": "risk_accepted"}},
            )
            assert published.status_code == 200, published.text
            store.create_sink(collector["id"], cipher=CredentialCipher(tmp_path / "cipher.key"),
                              url="https://hooks.example.com/extrio", secret="fixture-only")
            worker = Worker.__new__(Worker)
            worker.store, worker.contracts = store, app_module.contracts
            worker.runtime = CrawleeRuntime(tmp_path / "artifacts")
            runs = []
            for phase in range(3):
                state["phase"] = phase
                operation = client.post(
                    f"/api/v1/collectors/{collector['id']}/runs",
                    headers={"Idempotency-Key": f"incremental-e2e-run-{phase}"},
                )
                assert operation.status_code == 202, operation.text
                job = store.claim_job(60)
                assert job and job["operationId"] == operation.json()["id"]
                await worker.process(job)
                run = store.get_run(operation.json()["resourceId"])
                assert run["status"] == "succeeded"
                assert run["integrityStatus"] == "verified"
                assert run["listPagesFetched"] == 3
                assert run["checkpointAfter"]["watermark"] == today.isoformat()
                if coverage_mode == 'observed':
                    assert run['checkpointAfter']['kind'] == 'coverage'
                assert run["recordsOutsideWindow"] == 2
                assert run["paginationStopReason"] == ("time_window_reached" if phase == 0 else "checkpoint_reached")
                assert run["executionMode"] == ("initial" if phase == 0 else "incremental")
                runs.append(run)
            assert (runs[0]["newItems"], runs[0]["updatedItems"], runs[0]["unchangedItems"]) == (2, 0, 0)
            assert (runs[1]["newItems"], runs[1]["updatedItems"], runs[1]["unchangedItems"]) == (2, 1, 1)
            assert (runs[2]["newItems"], runs[2]["updatedItems"], runs[2]["unchangedItems"]) == (0, 0, 4)
            assert runs[1]["duplicateDetailUrls"] == runs[2]["duplicateDetailUrls"] == 1
            assert runs[1]["checkpointBefore"] == runs[0]["checkpointAfter"]
            assert runs[2]["checkpointBefore"] == runs[1]["checkpointAfter"]
            assert runs[1]["windowStart"] == (today - timedelta(days=3)).isoformat()
            by_title = {i["title"]: i for i in runs[1]["items"]}
            assert by_title["A"]["revision"] == 2 and by_title["late"]["changeType"] == "new"
            assert all(i["revision"] == by_title[i["title"]]["revision"] for i in runs[2]["items"])
            assert len(store.list_deliveries_for_collector(collector["id"])) == 5
            assert not any(path.startswith("/detail/old-") for path in state["requests"])
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
