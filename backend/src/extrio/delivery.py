"""Asynchronous webhook delivery engine.

Builds flat JSON payloads for claimed deliveries, serializes them once,
signs the exact bytes with the sink's HMAC-SHA256 secret, POSTs them with
idempotency and digest headers, and applies the retry/backoff/dead-letter
state machine on top of the store's delivery API.

Secrets and payloads are never logged; only delivery id, sink id, and
status codes are.
"""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from extrio.credentials import CredentialCipher
from extrio.store import Store

logger = logging.getLogger("extrio.delivery")

MAX_DELIVERY_ATTEMPTS = 5
BACKOFF_SCHEDULE_SECONDS = (60, 300, 1800, 7200, 21600)
DELIVERY_TIMEOUT_SECONDS = 10.0
USER_AGENT = "Extrio/1.0 (+webhook)"
EVENT_TYPE_ACCEPTED = "item.accepted"
EVENT_TYPE_TEST = "test.ping"
TEST_ITEM_EVENT_PREFIX = "test_"
OUTCOME_DELIVERED = "delivered"
OUTCOME_RETRY_SCHEDULED = "retry_scheduled"
OUTCOME_DEAD_LETTERED = "dead_lettered"
OUTCOME_ERROR = "error"
ERROR_TEXT_LIMIT = 300


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def is_test_delivery(delivery: dict[str, Any]) -> bool:
    """A synthetic sink test is marked by a ``test_`` item-event id (or a ``data.kind`` marker)."""

    data = delivery.get("data")
    if isinstance(data, dict) and data.get("kind") == "test":
        return True
    item_event_id = str(delivery.get("itemEventId") or "")
    return item_event_id == "test" or item_event_id.startswith(TEST_ITEM_EVENT_PREFIX)


def build_test_payload(delivery: dict[str, Any]) -> dict[str, Any]:
    """Minimal synthetic body for sink connectivity checks; never a contract item event."""

    return {
        "deliveryId": delivery["id"],
        "sinkId": delivery["sinkId"],
        "collectorId": delivery["collectorId"],
        "eventType": EVENT_TYPE_TEST,
        "kind": "test",
        "message": "Extrio webhook test delivery. This is not an item event.",
        "sentAt": utc_now_iso(),
    }


def build_event_payload(delivery: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Flat, n8n-friendly JSON body describing one accepted item event."""

    extracted = item.get("extractedData")
    return {
        "deliveryId": delivery["id"],
        "eventId": item["id"],
        "eventType": EVENT_TYPE_ACCEPTED,
        "changeType": item.get("changeType"),
        "collectorId": item.get("collectorId") or delivery.get("collectorId"),
        "collectorName": item.get("collectorName") or "",
        "entityKey": item.get("entityKey"),
        "revision": item.get("revision"),
        "decision": item.get("decision"),
        "title": item.get("title"),
        "publishedAt": item.get("publishedAt"),
        "observedAt": item.get("observedAt"),
        "sourceUrl": item.get("sourceUrl"),
        "extractedData": extracted if isinstance(extracted, dict) else {},
    }


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize exactly once; the returned bytes are both signed and sent."""

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def sign_body(body: bytes, secret: str) -> str:
    """``sha256=<hex hmac-sha256 of body with secret>``; an empty secret still yields a stable signature."""

    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def content_digest(body: bytes) -> str:
    return f"sha256={hashlib.sha256(body).hexdigest()}"


def webhook_headers(delivery_id: str, signature: str, digest: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Extrio-Signature": signature,
        "X-Extrio-Delivery-Id": delivery_id,
        "Idempotency-Key": delivery_id,
        "Content-Digest": digest,
        "User-Agent": USER_AGENT,
    }


def backoff_seconds(attempt_no: int) -> int:
    """Delay inserted after failed ``attempt_no`` before the next attempt (1m/5m/30m/2h/6h)."""

    return BACKOFF_SCHEDULE_SECONDS[min(attempt_no, len(BACKOFF_SCHEDULE_SECONDS)) - 1]


class WebhookDispatcher:
    """Executes claimed deliveries against their webhook sinks.

    The dispatcher never raises for a single delivery: every failure path ends
    in the store state machine (retry with backoff, or dead-letter). HTTP is
    performed synchronously; the worker runs batches through
    ``asyncio.to_thread``. ``transport`` is injectable so tests can use
    ``httpx.MockTransport``.
    """

    def __init__(
        self,
        store: Store,
        cipher: CredentialCipher,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DELIVERY_TIMEOUT_SECONDS,
    ) -> None:
        self.store = store
        self.cipher = cipher
        self.transport = transport
        self.timeout = timeout

    def process_batch(self, deliveries: list[dict[str, Any]]) -> list[str]:
        """Deliver a claimed batch over one shared HTTP client."""

        outcomes: list[str] = []
        if not deliveries:
            return outcomes
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            for delivery in deliveries:
                outcomes.append(self.process(delivery, client=client))
        return outcomes

    def process(self, delivery: dict[str, Any], *, client: httpx.Client | None = None) -> str:
        """Deliver exactly one claimed delivery; never raises."""

        try:
            if client is None:
                with self._new_client() as own_client:
                    return self._deliver(delivery, own_client)
            return self._deliver(delivery, client)
        except Exception as exc:  # noqa: BLE001 - one crashing delivery must not kill the worker
            logger.exception("Delivery dispatch crashed delivery=%s sink=%s", delivery.get("id"), delivery.get("sinkId"))
            try:
                message = f"dispatcher error: {type(exc).__name__}: {exc}"[:ERROR_TEXT_LIMIT]
                return self._record_failure(delivery, status_code=None, error=message)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to record crashed attempt delivery=%s", delivery.get("id"))
                return OUTCOME_ERROR

    def _new_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=self.transport)

    def _deliver(self, delivery: dict[str, Any], client: httpx.Client) -> str:
        delivery_id = str(delivery["id"])
        sink_id = str(delivery["sinkId"])
        sink = self.store.get_sink(sink_id, cipher=self.cipher)
        if sink is None:
            return self._dead_letter(delivery, error="sink deleted before delivery")
        if not sink["enabled"]:
            return self._dead_letter(delivery, error="sink disabled before delivery")
        if sink.get("type") != "webhook":
            return self._dead_letter(delivery, error=f"unsupported sink type: {sink.get('type')}")
        if int(delivery.get("attemptCount", 0)) >= MAX_DELIVERY_ATTEMPTS:
            return self._dead_letter(delivery, error=f"exceeded {MAX_DELIVERY_ATTEMPTS} delivery attempts")

        payload = self._build_payload(delivery)
        if payload is None:
            return self._dead_letter(delivery, error=f"referenced item {delivery['itemEventId']} not found")

        body = serialize_payload(payload)
        headers = webhook_headers(delivery_id, sign_body(body, str(sink.get("secret") or "")), content_digest(body))
        status_code, error = self._post(client, str(sink["url"]), body, headers)

        if error is None:
            self.store.record_delivery_attempt(delivery_id, status_code=status_code)
            self.store.mark_delivery_delivered(delivery_id)
            logger.info("Delivered delivery=%s sink=%s status_code=%s", delivery_id, sink_id, status_code)
            return OUTCOME_DELIVERED
        if status_code is not None and 400 <= status_code < 500 and status_code != 429:
            self.store.record_delivery_attempt(delivery_id, status_code=status_code, error=error)
            return self._dead_letter(delivery, error=error)
        return self._record_failure(delivery, status_code=status_code, error=error)

    def _build_payload(self, delivery: dict[str, Any]) -> dict[str, Any] | None:
        if is_test_delivery(delivery):
            return build_test_payload(delivery)
        item = self.store.get_item(str(delivery["itemEventId"]))
        if item is None:
            return None
        return build_event_payload(delivery, item)

    @staticmethod
    def _post(client: httpx.Client, url: str, body: bytes, headers: dict[str, str]) -> tuple[int | None, str | None]:
        try:
            response = client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            return None, f"request failed: {type(exc).__name__}: {exc}"[:ERROR_TEXT_LIMIT]
        status_code = int(response.status_code)
        if 200 <= status_code < 300:
            return status_code, None
        return status_code, f"unexpected response status {status_code}"

    def _record_failure(self, delivery: dict[str, Any], *, status_code: int | None, error: str) -> str:
        delivery_id = str(delivery["id"])
        attempt_no = int(delivery.get("attemptCount", 0)) + 1
        if attempt_no >= MAX_DELIVERY_ATTEMPTS:
            self.store.record_delivery_attempt(delivery_id, status_code=status_code, error=error[:ERROR_TEXT_LIMIT])
            return self._dead_letter(delivery, error=error)
        delay = backoff_seconds(attempt_no)
        next_attempt_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
        self.store.record_delivery_attempt(
            delivery_id, status_code=status_code, error=error[:ERROR_TEXT_LIMIT], next_attempt_at=next_attempt_at
        )
        logger.warning(
            "Delivery failed delivery=%s sink=%s status_code=%s retry_in_seconds=%s",
            delivery_id,
            delivery.get("sinkId"),
            status_code,
            delay,
        )
        return OUTCOME_RETRY_SCHEDULED

    def _dead_letter(self, delivery: dict[str, Any], *, error: str) -> str:
        self.store.mark_delivery_dead_lettered(str(delivery["id"]), error=error[:ERROR_TEXT_LIMIT])
        logger.warning("Dead-lettered delivery=%s sink=%s error=%s", delivery.get("id"), delivery.get("sinkId"), error[:ERROR_TEXT_LIMIT])
        return OUTCOME_DEAD_LETTERED
