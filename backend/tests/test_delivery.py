import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from extrio.credentials import CredentialCipher
from extrio.delivery import (
    BACKOFF_SCHEDULE_SECONDS,
    MAX_DELIVERY_ATTEMPTS,
    OUTCOME_DEAD_LETTERED,
    OUTCOME_DELIVERED,
    OUTCOME_RETRY_SCHEDULED,
    WebhookDispatcher,
    build_event_payload,
    is_test_delivery,
    serialize_payload,
)
from extrio.store import Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "delivery.db")
    store.initialize()
    return store


def accepted_item(item_id: str, collector_id: str, run_id: str = "run_delivery") -> dict[str, Any]:
    return {
        "id": item_id,
        "collectorId": collector_id,
        "collectorName": "Demo",
        "runId": run_id,
        "decision": "accepted",
        "changeType": "new",
        "entityKey": "entity_delivery",
        "revision": 1,
        "title": "招标公告 A",
        "publishedAt": "2026-08-30",
        "observedAt": "2026-08-31 08:00",
        "sourceUrl": "https://example.com/detail/a",
        "extractedData": {"buyer": "Buyer", "budget": "100"},
        "lineage": {"runId": run_id},
    }


class _CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        self.server.requests.append({"body": self.rfile.read(length), "headers": dict(self.headers.items())})
        self.send_response(self.server.response_status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def http_sink() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    server.requests = []
    server.response_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def make_delivery_chain(
    tmp_path: Path, http_sink: HTTPServer | None = None
) -> tuple[Store, CredentialCipher, dict[str, Any], dict[str, Any], dict[str, Any]]:
    store = make_store(tmp_path)
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    url = f"http://127.0.0.1:{http_sink.server_address[1]}/hook" if http_sink else "http://127.0.0.1:9/hook"
    sink = store.create_sink(collector["id"], cipher=cipher, url=url, secret="s3cret")
    item = accepted_item("item_delivery_1", collector["id"])
    store.save_run({"id": item["runId"], "collectorId": collector["id"], "status": "succeeded"})
    store.save_items(item["runId"], [item])
    delivery = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id=item["id"])
    return store, cipher, collector, sink, delivery


def lower_headers(raw_headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in raw_headers.items()}


def test_delivered_payload_is_signed_verifiable_and_attempt_recorded(tmp_path: Path, http_sink: HTTPServer) -> None:
    store, cipher, collector, sink, delivery = make_delivery_chain(tmp_path, http_sink)
    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1 and claimed[0]["sinkUrl"] == sink["url"]

    outcome = WebhookDispatcher(store, cipher).process(claimed[0])

    assert outcome == OUTCOME_DELIVERED
    view = store.get_delivery(delivery["id"])
    assert view is not None and view["status"] == "delivered" and view["lastStatusCode"] == 200
    assert view["nextAttemptAt"] is None
    attempts = store.list_delivery_attempts(delivery["id"])
    assert [attempt["attemptNo"] for attempt in attempts] == [1]
    assert attempts[0]["statusCode"] == 200 and attempts[0]["error"] is None

    received = http_sink.requests[0]
    body = received["body"]
    payload = json.loads(body)
    assert payload["deliveryId"] == delivery["id"]
    assert payload["eventId"] == "item_delivery_1"
    assert payload["eventType"] == "item.accepted"
    assert payload["changeType"] == "new"
    assert payload["collectorId"] == collector["id"]
    assert payload["collectorName"] == "Demo"
    assert payload["entityKey"] == "entity_delivery"
    assert payload["revision"] == 1
    assert payload["decision"] == "accepted"
    assert payload["title"] == "招标公告 A"
    assert payload["publishedAt"] == "2026-08-30"
    assert payload["observedAt"] == "2026-08-31 08:00"
    assert payload["sourceUrl"] == "https://example.com/detail/a"
    assert payload["extractedData"] == {"buyer": "Buyer", "budget": "100"}

    headers = lower_headers(received["headers"])
    expected_signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert headers["x-extrio-signature"] == expected_signature
    assert headers["content-digest"] == f"sha256={hashlib.sha256(body).hexdigest()}"
    assert headers["x-extrio-delivery-id"] == delivery["id"]
    assert headers["idempotency-key"] == delivery["id"]
    assert headers["content-type"] == "application/json"
    assert headers["user-agent"] == "Extrio/1.0 (+webhook)"


def test_serialization_keeps_non_ascii_characters_unescaped() -> None:
    payload = build_event_payload({"id": "delivery_x", "collectorId": "collector_x"}, {"id": "item_x", "title": "招标公告"})
    body = serialize_payload(payload)
    assert "招标公告".encode() in body
    assert b"\\u" not in body


def test_server_error_schedules_retry_with_first_backoff_step(tmp_path: Path, http_sink: HTTPServer) -> None:
    store, cipher, _collector, _sink, delivery = make_delivery_chain(tmp_path, http_sink)
    http_sink.response_status = 500
    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1

    outcome = WebhookDispatcher(store, cipher).process(claimed[0])

    assert outcome == OUTCOME_RETRY_SCHEDULED
    view = store.get_delivery(delivery["id"])
    assert view is not None and view["status"] == "failed" and view["lastStatusCode"] == 500
    assert "500" in (view["lastError"] or "")
    attempts = store.list_delivery_attempts(delivery["id"])
    assert [attempt["attemptNo"] for attempt in attempts] == [1]
    assert attempts[0]["statusCode"] == 500 and attempts[0]["error"]
    expected_next = datetime.now(UTC) + timedelta(seconds=BACKOFF_SCHEDULE_SECONDS[0])
    next_attempt = datetime.fromisoformat((view["nextAttemptAt"] or "").replace("Z", "+00:00"))
    assert abs((next_attempt - expected_next).total_seconds()) < 30
    # Not claimable again until the backoff window elapses.
    assert store.claim_due_deliveries(10, now=datetime.now(UTC) + timedelta(seconds=BACKOFF_SCHEDULE_SECONDS[0] - 1)) == []


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_retryable_status_codes_schedule_backoff(tmp_path: Path, status_code: int) -> None:
    store, cipher, _collector, _sink, _delivery = make_delivery_chain(tmp_path)
    transport = httpx.MockTransport(lambda _request: httpx.Response(status_code))
    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1

    outcome = WebhookDispatcher(store, cipher, transport=transport).process(claimed[0])

    assert outcome == OUTCOME_RETRY_SCHEDULED


def test_permanent_client_error_dead_letters_immediately(tmp_path: Path, http_sink: HTTPServer) -> None:
    store, cipher, _collector, _sink, delivery = make_delivery_chain(tmp_path, http_sink)
    http_sink.response_status = 404
    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1

    outcome = WebhookDispatcher(store, cipher).process(claimed[0])

    assert outcome == OUTCOME_DEAD_LETTERED
    view = store.get_delivery(delivery["id"])
    assert view is not None and view["status"] == "dead_lettered" and view["lastStatusCode"] == 404
    assert [attempt["attemptNo"] for attempt in store.list_delivery_attempts(delivery["id"])] == [1]


def test_five_failed_attempts_dead_letter(tmp_path: Path, http_sink: HTTPServer) -> None:
    store, cipher, _collector, _sink, delivery = make_delivery_chain(tmp_path, http_sink)
    http_sink.response_status = 500
    dispatcher = WebhookDispatcher(store, cipher)
    claim_now = datetime.now(UTC)

    for round_no in range(MAX_DELIVERY_ATTEMPTS):
        claimed = store.claim_due_deliveries(10, now=claim_now)
        assert len(claimed) == 1
        outcome = dispatcher.process(claimed[0])
        if round_no == MAX_DELIVERY_ATTEMPTS - 1:
            assert outcome == OUTCOME_DEAD_LETTERED
        else:
            assert outcome == OUTCOME_RETRY_SCHEDULED
            claim_now += timedelta(seconds=BACKOFF_SCHEDULE_SECONDS[round_no] + 1)

    view = store.get_delivery(delivery["id"])
    assert view is not None and view["status"] == "dead_lettered"
    assert [attempt["attemptNo"] for attempt in store.list_delivery_attempts(delivery["id"])] == [1, 2, 3, 4, 5]
    # Dead-lettered deliveries are never claimed again.
    assert store.claim_due_deliveries(10, now=claim_now + timedelta(days=365)) == []


def test_network_error_is_recorded_as_retryable_attempt(tmp_path: Path) -> None:
    store, cipher, _collector, _sink, delivery = make_delivery_chain(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    dispatcher = WebhookDispatcher(store, cipher, transport=httpx.MockTransport(handler))
    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1

    outcome = dispatcher.process(claimed[0])

    assert outcome == OUTCOME_RETRY_SCHEDULED
    view = store.get_delivery(delivery["id"])
    assert view is not None and view["status"] == "failed" and view["lastStatusCode"] is None
    attempts = store.list_delivery_attempts(delivery["id"])
    assert attempts[0]["statusCode"] is None and "ConnectError" in (attempts[0]["error"] or "")


def test_disabled_sink_dead_letters_without_http_call(tmp_path: Path, http_sink: HTTPServer) -> None:
    store, cipher, _collector, sink, delivery = make_delivery_chain(tmp_path, http_sink)
    store.update_sink(sink["id"], enabled=False)

    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1

    outcome = WebhookDispatcher(store, cipher).process(claimed[0])

    assert outcome == OUTCOME_DEAD_LETTERED
    view = store.get_delivery(delivery["id"])
    assert view is not None and view["status"] == "dead_lettered" and "disabled" in (view["lastError"] or "")
    assert http_sink.requests == []
    assert store.list_delivery_attempts(delivery["id"]) == []


def test_test_kind_delivery_sends_minimal_synthetic_payload(tmp_path: Path, http_sink: HTTPServer) -> None:
    store = make_store(tmp_path)
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    sink = store.create_sink(collector["id"], cipher=cipher, url=f"http://127.0.0.1:{http_sink.server_address[1]}/hook", secret="s3cret")
    delivery = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="test_connectivity_1")
    assert is_test_delivery({"itemEventId": "test_connectivity_1"}) is True
    assert is_test_delivery({"itemEventId": "item_real_1", "data": {"kind": "test"}}) is True
    assert is_test_delivery({"itemEventId": "item_real_1"}) is False

    claimed = store.claim_due_deliveries(10)
    assert len(claimed) == 1

    outcome = WebhookDispatcher(store, cipher).process(claimed[0])

    assert outcome == OUTCOME_DELIVERED
    payload = json.loads(http_sink.requests[0]["body"])
    assert payload["kind"] == "test"
    assert payload["eventType"] == "test.ping"
    assert payload["deliveryId"] == delivery["id"]
    assert payload["sinkId"] == sink["id"]
    assert payload["collectorId"] == collector["id"]
    assert "eventId" not in payload and "entityKey" not in payload
    headers = lower_headers(http_sink.requests[0]["headers"])
    body = http_sink.requests[0]["body"]
    assert headers["x-extrio-signature"] == "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
