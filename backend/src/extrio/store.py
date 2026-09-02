import hashlib
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

TERMINAL_OPERATION_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
NONTERMINAL_RUN_STATUSES = {"queued", "running", "finalizing"}
DEFAULT_COLLECTION_POLICY = {
    "mode": "rolling_incremental",
    "initialWindowDays": 30,
    "lookbackDays": 3,
    "consecutiveOlderPages": 2,
    "maxPages": 20,
    "maxItems": 300,
    "timezone": "Asia/Shanghai",
}
DEFAULT_COLLECTOR_SCHEDULE = {
    "enabled": False,
    "cronExpression": "0 8 * * *",
    "timezone": "Asia/Shanghai",
    "overlapPolicy": "forbid",
}
DEFAULT_COLLECTION_ID = "collection_nationwide_tender"
DEFAULT_COLLECTION_NAME = "全国公共资源交易标讯"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, value: str | None = None, length: int = 16) -> str:
    seed = value or uuid.uuid4().hex
    token = re.sub(r"[^a-z0-9_]", "_", seed.lower()).strip("_")
    if not token or not token[0].isalpha():
        token = f"x_{token}"
    return f"{prefix}_{token[:length]}"


def payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyConflict(Exception):
    pass


class AuthSetupComplete(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._init_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._init_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS collectors (
                        id TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS operations (
                        id TEXT PRIMARY KEY,
                        collector_id TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (collector_id) REFERENCES collectors(id)
                    );
                    CREATE TABLE IF NOT EXISTS runs (
                        id TEXT PRIMARY KEY,
                        collector_id TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (collector_id) REFERENCES collectors(id)
                    );
                    CREATE TABLE IF NOT EXISTS items (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES runs(id)
                    );
                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        operation_id TEXT NOT NULL UNIQUE,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'queued',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        available_at TEXT NOT NULL,
                        lease_until TEXT,
                        last_error TEXT,
                        FOREIGN KEY (operation_id) REFERENCES operations(id)
                    );
                    CREATE TABLE IF NOT EXISTS idempotency (
                        scope TEXT NOT NULL,
                        key TEXT NOT NULL,
                        request_hash TEXT NOT NULL,
                        status_code INTEGER NOT NULL,
                        response TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (scope, key)
                    );
                    CREATE TABLE IF NOT EXISTS signing_keys (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS rule_versions (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        collector_id TEXT NOT NULL,
                        rule_digest TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (collector_id) REFERENCES collectors(id)
                    );
                    CREATE TABLE IF NOT EXISTS rule_attestations (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        rule_version_id TEXT NOT NULL,
                        rule_digest TEXT NOT NULL,
                        key_id TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (rule_version_id) REFERENCES rule_versions(id),
                        FOREIGN KEY (key_id) REFERENCES signing_keys(id)
                    );
                    CREATE TABLE IF NOT EXISTS audit_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        id TEXT NOT NULL UNIQUE,
                        tenant_id TEXT NOT NULL,
                        event_hash TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS collection_policies (
                        id TEXT PRIMARY KEY,
                        collector_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        policy_digest TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(collector_id, version),
                        FOREIGN KEY (collector_id) REFERENCES collectors(id)
                    );
                    CREATE TABLE IF NOT EXISTS collector_checkpoints (
                        collector_id TEXT PRIMARY KEY,
                        policy_version_id TEXT NOT NULL,
                        data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (collector_id) REFERENCES collectors(id),
                        FOREIGN KEY (policy_version_id) REFERENCES collection_policies(id)
                    );
                    CREATE TABLE IF NOT EXISTS collector_schedules (
                        id TEXT PRIMARY KEY,
                        collector_id TEXT NOT NULL UNIQUE,
                        revision INTEGER NOT NULL,
                        enabled INTEGER NOT NULL,
                        next_run_at TEXT,
                        last_triggered_at TEXT,
                        data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (collector_id) REFERENCES collectors(id)
                    );
                    CREATE TABLE IF NOT EXISTS schedule_occurrences (
                        occurrence_key TEXT PRIMARY KEY,
                        schedule_id TEXT NOT NULL,
                        collector_id TEXT NOT NULL,
                        scheduled_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        run_id TEXT,
                        reason TEXT,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (schedule_id) REFERENCES collector_schedules(id),
                        FOREIGN KEY (collector_id) REFERENCES collectors(id)
                    );
                    CREATE TABLE IF NOT EXISTS platform_settings (
                        key TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS auth_users (
                        id TEXT PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS auth_sessions (
                        token_hash TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, available_at, lease_until);
                    CREATE INDEX IF NOT EXISTS idx_runs_collector ON runs(collector_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_items_run ON items(run_id);
                    CREATE INDEX IF NOT EXISTS idx_rule_versions_collector ON rule_versions(collector_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_rule_attestations_rule ON rule_attestations(rule_version_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id, sequence DESC);
                    CREATE INDEX IF NOT EXISTS idx_collection_policies_collector ON collection_policies(collector_id, version DESC);
                    CREATE INDEX IF NOT EXISTS idx_collector_schedules_due ON collector_schedules(enabled, next_run_at);
                    CREATE INDEX IF NOT EXISTS idx_schedule_occurrences_collector ON schedule_occurrences(collector_id, scheduled_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
                    CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
                    CREATE TRIGGER IF NOT EXISTS rule_versions_immutable_update
                    BEFORE UPDATE ON rule_versions BEGIN SELECT RAISE(ABORT, 'rule_versions are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS rule_versions_immutable_delete
                    BEFORE DELETE ON rule_versions BEGIN SELECT RAISE(ABORT, 'rule_versions are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS rule_attestations_immutable_update
                    BEFORE UPDATE ON rule_attestations BEGIN SELECT RAISE(ABORT, 'rule_attestations are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS rule_attestations_immutable_delete
                    BEFORE DELETE ON rule_attestations BEGIN SELECT RAISE(ABORT, 'rule_attestations are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS audit_events_immutable_update
                    BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS audit_events_immutable_delete
                    BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS collection_policies_immutable_update
                    BEFORE UPDATE ON collection_policies BEGIN SELECT RAISE(ABORT, 'collection_policies are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS collection_policies_immutable_delete
                    BEFORE DELETE ON collection_policies BEGIN SELECT RAISE(ABORT, 'collection_policies are immutable'); END;
                    """
                )

    @staticmethod
    def _auth_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "role": row["role"],
        }

    def auth_setup_required(self) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone() is None

    def create_first_auth_user(
        self,
        *,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> dict[str, Any]:
        now = utc_now()
        user_id = stable_id("user", uuid.uuid4().hex, 32)
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone() is not None:
                raise AuthSetupComplete
            connection.execute(
                """
                INSERT INTO auth_users(id, username, password_hash, role, display_name, created_at, updated_at)
                VALUES(?, ?, ?, 'administrator', ?, ?, ?)
                """,
                (user_id, username, password_hash, display_name, now, now),
            )
            row = connection.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
        user = self._auth_user(row)
        if user is None:
            raise RuntimeError("created authentication user is unavailable")
        return user

    def get_auth_credentials(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE username=? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if row is None:
            return None
        user = self._auth_user(row)
        return {**user, "passwordHash": row["password_hash"]} if user else None

    def create_auth_session(self, *, token_hash: str, user_id: str, expires_at: str) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
            connection.execute(
                """
                INSERT INTO auth_sessions(token_hash, user_id, expires_at, created_at, last_seen_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (token_hash, user_id, expires_at, now, now),
            )

    def get_auth_session(self, token_hash: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT u.*
                FROM auth_sessions s
                JOIN auth_users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>?
                """,
                (token_hash, now),
            ).fetchone()
        return self._auth_user(row)

    def delete_auth_session(self, token_hash: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))

    def get_platform_setting(self, key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM platform_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["data"]) if row else None

    def save_platform_setting(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        payload = {**value, "updatedAt": now}
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO platform_settings(key, data, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (key, json.dumps(payload, ensure_ascii=False), now),
            )
        return payload

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return json.loads(row["data"]) if row else None

    @staticmethod
    def _decode_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        run = json.loads(row["data"])
        run["startedAtIso"] = row["created_at"]
        return run

    def list_collectors(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM collectors ORDER BY created_at DESC").fetchall()
        return [json.loads(row["data"]) for row in rows]

    def get_collector(self, collector_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM collectors WHERE id=?", (collector_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM collectors WHERE id=?", (collector_id,)).fetchone())

    def save_collector(self, collector: dict[str, Any], connection: sqlite3.Connection | None = None) -> None:
        now = utc_now()
        payload = json.dumps(collector, ensure_ascii=False)
        sql = """
            INSERT INTO collectors(id, data, created_at, updated_at) VALUES(?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (collector["id"], payload, now, now)
        if connection is not None:
            connection.execute(sql, params)
            return
        with self.transaction() as own:
            own.execute(sql, params)

    def source_exists(
        self,
        source_url: str,
        connection: sqlite3.Connection | None = None,
        *,
        exclude_collector_id: str | None = None,
    ) -> bool:
        query = "SELECT 1 FROM collectors WHERE json_extract(data, '$.sourceUrl')=?"
        params: tuple[str, ...] = (source_url,)
        if exclude_collector_id:
            query += " AND id<>?"
            params = (source_url, exclude_collector_id)
        query += " LIMIT 1"
        if connection is not None:
            return connection.execute(query, params).fetchone() is not None
        with self.connect() as own:
            return own.execute(query, params).fetchone() is not None

    def create_collector(
        self,
        name: str,
        intent: str,
        source_url: str,
        source_host: str,
        *,
        collection_id: str = DEFAULT_COLLECTION_ID,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        collection_version: str = "tender_notice_v4",
    ) -> dict[str, Any]:
        collector = {
            "id": stable_id("collector", f"{source_host}_{uuid.uuid4().hex[:8]}", 40),
            "name": name,
            "intent": intent,
            "sourceUrl": source_url,
            "sourceHost": source_host,
            "status": "draft",
            "collectionId": collection_id,
            "collectionName": collection_name,
            "collectionVersion": collection_version,
            "activeRuleVersion": None,
            "activeOperationId": None,
            "latestRunId": None,
            "updatedAt": utc_now(),
            "candidate": None,
            "previewItems": [],
            "reviewDecisions": None,
            "activeCollectionPolicyId": None,
            "collectionPolicy": None,
            "checkpoint": None,
        }
        self.save_collector(collector)
        self.create_collection_policy(collector["id"], DEFAULT_COLLECTION_POLICY)
        return self.ensure_schedule(collector["id"])

    @staticmethod
    def validate_collection_policy(values: dict[str, Any]) -> dict[str, Any]:
        expected = set(DEFAULT_COLLECTION_POLICY)
        if set(values) != expected or values.get("mode") != "rolling_incremental" or values.get("timezone") != "Asia/Shanghai":
            raise ValueError("collection policy fields are invalid")
        ranges = {
            "initialWindowDays": (1, 3650),
            "lookbackDays": (0, 90),
            "consecutiveOlderPages": (1, 10),
            "maxPages": (1, 1000),
            "maxItems": (1, 100_000),
        }
        for key, (minimum, maximum) in ranges.items():
            value = values.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
                raise ValueError(f"collection policy {key} is out of range")
        return dict(values)

    def create_collection_policy(self, collector_id: str, values: dict[str, Any]) -> dict[str, Any]:
        normalized = self.validate_collection_policy(values)
        with self.transaction() as connection:
            collector = self.get_collector(collector_id, connection)
            if collector is None:
                raise KeyError(collector_id)
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM collection_policies WHERE collector_id=?",
                (collector_id,),
            ).fetchone()
            version = int(row["version"]) + 1
            policy_id = stable_id("policy", f"{collector_id.removeprefix('collector_')}_v{version}", 120)
            created_at = utc_now()
            policy = {
                "id": policy_id,
                "collectorId": collector_id,
                "version": version,
                **normalized,
                "createdAt": created_at,
            }
            policy["digest"] = f"sha256:{payload_hash(policy)}"
            connection.execute(
                "INSERT INTO collection_policies(id, collector_id, version, policy_digest, data, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (policy_id, collector_id, version, policy["digest"], json.dumps(policy, ensure_ascii=False), created_at),
            )
            connection.execute("DELETE FROM collector_checkpoints WHERE collector_id=?", (collector_id,))
            collector.update(activeCollectionPolicyId=policy_id, collectionPolicy=policy, checkpoint=None, updatedAt="刚刚")
            self.save_collector(collector, connection)
            return collector

    def ensure_collection_policy(self, collector_id: str) -> dict[str, Any]:
        collector = self.get_collector(collector_id)
        if collector is None:
            raise KeyError(collector_id)
        if collector.get("collectionPolicy") and collector.get("activeCollectionPolicyId"):
            return collector
        return self.create_collection_policy(collector_id, DEFAULT_COLLECTION_POLICY)

    def get_collection_policy(self, policy_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        query = "SELECT data FROM collection_policies WHERE id=?"
        if connection is not None:
            return self._decode(connection.execute(query, (policy_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute(query, (policy_id,)).fetchone())

    def get_checkpoint(self, collector_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        query = "SELECT data FROM collector_checkpoints WHERE collector_id=?"
        if connection is not None:
            return self._decode(connection.execute(query, (collector_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute(query, (collector_id,)).fetchone())

    @staticmethod
    def validate_schedule(values: dict[str, Any]) -> dict[str, Any]:
        expected = set(DEFAULT_COLLECTOR_SCHEDULE)
        if set(values) != expected:
            raise ValueError("schedule fields are invalid")
        if not isinstance(values.get("enabled"), bool):
            raise ValueError("schedule enabled must be a boolean")
        if values.get("timezone") != "Asia/Shanghai" or values.get("overlapPolicy") != "forbid":
            raise ValueError("schedule timezone or overlap policy is invalid")
        expression = str(values.get("cronExpression", "")).strip()
        if len(expression.split()) != 5 or not croniter.is_valid(expression):
            raise ValueError("schedule cron expression must use a valid five-field format")
        return {**values, "cronExpression": expression}

    @staticmethod
    def next_schedule_time(expression: str, timezone: str, base: datetime | None = None) -> str:
        current = base or datetime.now(ZoneInfo(timezone))
        if current.tzinfo is None:
            current = current.replace(tzinfo=ZoneInfo(timezone))
        next_local = croniter(expression, current.astimezone(ZoneInfo(timezone))).get_next(datetime)
        return next_local.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def save_schedule(self, collector_id: str, values: dict[str, Any]) -> dict[str, Any]:
        normalized = self.validate_schedule(values)
        with self.transaction() as connection:
            collector = self.get_collector(collector_id, connection)
            if collector is None:
                raise KeyError(collector_id)
            existing_row = connection.execute("SELECT data FROM collector_schedules WHERE collector_id=?", (collector_id,)).fetchone()
            existing = self._decode(existing_row)
            revision = int(existing.get("revision", 0)) + 1 if existing else 1
            schedule_id = existing.get("id") if existing else stable_id("schedule", collector_id.removeprefix("collector_"), 120)
            updated_at = utc_now()
            schedule = {
                "id": schedule_id,
                "collectorId": collector_id,
                "revision": revision,
                **normalized,
                "lastTriggeredAt": existing.get("lastTriggeredAt") if existing else None,
                "nextRunAt": self.next_schedule_time(normalized["cronExpression"], normalized["timezone"])
                if normalized["enabled"]
                else None,
                "updatedAt": updated_at,
            }
            connection.execute(
                """
                INSERT INTO collector_schedules(id, collector_id, revision, enabled, next_run_at, last_triggered_at, data, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collector_id) DO UPDATE SET
                    revision=excluded.revision, enabled=excluded.enabled, next_run_at=excluded.next_run_at,
                    last_triggered_at=excluded.last_triggered_at, data=excluded.data, updated_at=excluded.updated_at
                """,
                (
                    schedule_id,
                    collector_id,
                    revision,
                    int(schedule["enabled"]),
                    schedule["nextRunAt"],
                    schedule["lastTriggeredAt"],
                    json.dumps(schedule, ensure_ascii=False),
                    updated_at,
                ),
            )
            collector.update(schedule=schedule, updatedAt="刚刚")
            self.save_collector(collector, connection)
            return collector

    def ensure_schedule(self, collector_id: str) -> dict[str, Any]:
        collector = self.get_collector(collector_id)
        if collector is None:
            raise KeyError(collector_id)
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM collector_schedules WHERE collector_id=?", (collector_id,)).fetchone()
        if row:
            schedule = self._decode(row)
            if collector.get("schedule") != schedule:
                collector["schedule"] = schedule
                self.save_collector(collector)
            return collector
        return self.save_schedule(collector_id, DEFAULT_COLLECTOR_SCHEDULE)

    def claim_due_schedules(self, now: datetime | None = None) -> list[dict[str, Any]]:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        instant_iso = instant.isoformat().replace("+00:00", "Z")
        claimed: list[dict[str, Any]] = []
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT data FROM collector_schedules WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at",
                (instant_iso,),
            ).fetchall()
            for row in rows:
                schedule = self._decode(row)
                scheduled_at = schedule["nextRunAt"]
                occurrence_seed = f"{schedule['id']}\n{schedule['revision']}\n{scheduled_at}"
                occurrence_key = f"occurrence_{payload_hash(occurrence_seed)[:32]}"
                created_at = utc_now()
                occurrence = {
                    "occurrenceKey": occurrence_key,
                    "scheduleId": schedule["id"],
                    "collectorId": schedule["collectorId"],
                    "scheduledAt": scheduled_at,
                    "status": "claimed",
                    "runId": None,
                    "reason": None,
                }
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO schedule_occurrences(
                        occurrence_key, schedule_id, collector_id, scheduled_at, status, run_id, reason, data, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        occurrence_key,
                        schedule["id"],
                        schedule["collectorId"],
                        scheduled_at,
                        "claimed",
                        None,
                        None,
                        json.dumps(occurrence, ensure_ascii=False),
                        created_at,
                        created_at,
                    ),
                )
                next_run_at = self.next_schedule_time(
                    schedule["cronExpression"],
                    schedule["timezone"],
                    instant,
                )
                schedule.update(lastTriggeredAt=scheduled_at, nextRunAt=next_run_at, updatedAt=created_at)
                connection.execute(
                    "UPDATE collector_schedules SET next_run_at=?, last_triggered_at=?, data=?, updated_at=? WHERE id=?",
                    (next_run_at, scheduled_at, json.dumps(schedule, ensure_ascii=False), created_at, schedule["id"]),
                )
                collector = self.get_collector(schedule["collectorId"], connection)
                if collector:
                    collector["schedule"] = schedule
                    self.save_collector(collector, connection)
                if inserted.rowcount:
                    claimed.append(occurrence)
        return claimed

    def finish_schedule_occurrence(self, occurrence_key: str, *, status: str, run_id: str | None, reason: str | None) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT data FROM schedule_occurrences WHERE occurrence_key=?", (occurrence_key,)).fetchone()
            if not row:
                raise KeyError(occurrence_key)
            occurrence = self._decode(row)
            occurrence.update(status=status, runId=run_id, reason=reason)
            connection.execute(
                "UPDATE schedule_occurrences SET status=?, run_id=?, reason=?, data=?, updated_at=? WHERE occurrence_key=?",
                (status, run_id, reason, json.dumps(occurrence, ensure_ascii=False), utc_now(), occurrence_key),
            )

    def save_checkpoint(self, checkpoint: dict[str, Any], connection: sqlite3.Connection | None = None) -> None:
        own_connection = connection is None
        target = connection or self.connect()
        try:
            if own_connection:
                target.execute("BEGIN IMMEDIATE")
            target.execute(
                """
                INSERT INTO collector_checkpoints(collector_id, policy_version_id, data, updated_at) VALUES(?, ?, ?, ?)
                ON CONFLICT(collector_id) DO UPDATE SET
                    policy_version_id=excluded.policy_version_id, data=excluded.data, updated_at=excluded.updated_at
                """,
                (checkpoint["collectorId"], checkpoint["policyVersionId"], json.dumps(checkpoint, ensure_ascii=False), utc_now()),
            )
            collector = self.get_collector(checkpoint["collectorId"], target)
            if collector is None:
                raise KeyError(checkpoint["collectorId"])
            collector["checkpoint"] = checkpoint
            self.save_collector(collector, target)
            if own_connection:
                target.commit()
        except Exception:
            if own_connection:
                target.rollback()
            raise
        finally:
            if own_connection:
                target.close()

    def get_operation(self, operation_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM operations WHERE id=?", (operation_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM operations WHERE id=?", (operation_id,)).fetchone())

    def list_operations(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM operations ORDER BY created_at DESC").fetchall()
        return [json.loads(row["data"]) for row in rows]

    def save_operation(self, operation: dict[str, Any], collector_id: str, connection: sqlite3.Connection | None = None) -> None:
        now = utc_now()
        sql = """
            INSERT INTO operations(id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (operation["id"], collector_id, json.dumps(operation, ensure_ascii=False), now, now)
        if connection is not None:
            connection.execute(sql, params)
            return
        with self.transaction() as own:
            own.execute(sql, params)

    def update_operation(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        with self.transaction() as connection:
            operation = self.get_operation(operation_id, connection)
            if operation is None:
                raise KeyError(operation_id)
            operation.update(changes)
            self.save_operation(operation, connection=connection, collector_id=self.operation_collector_id(operation_id, connection))
            return operation

    @staticmethod
    def operation_collector_id(operation_id: str, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT collector_id FROM operations WHERE id=?", (operation_id,)).fetchone()
        if not row:
            raise KeyError(operation_id)
        return str(row["collector_id"])

    def create_async_command(
        self,
        *,
        kind: str,
        collector_id: str,
        resource_type: str,
        resource_id: str,
        job_payload: dict[str, Any],
        collector_changes: dict[str, Any] | None = None,
        run: dict[str, Any] | None = None,
        activate_collector: bool = True,
    ) -> dict[str, Any]:
        operation_id = stable_id("op", uuid.uuid4().hex)
        operation = {
            "id": operation_id,
            "kind": kind,
            "status": "queued",
            "phase": "queued",
            "progress": 0,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "statusUrl": f"/api/v1/operations/{operation_id}",
            "pollAfterMs": 400,
            "metrics": {
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
            "error": None,
        }
        with self.transaction() as connection:
            if collector_changes or activate_collector:
                collector = self.get_collector(collector_id, connection)
                if collector is None:
                    raise KeyError(collector_id)
                collector.update(collector_changes or {})
                if activate_collector:
                    collector["activeOperationId"] = operation_id
                self.save_collector(collector, connection)
            if run is not None:
                run["operationId"] = operation_id
                self.save_run(run, connection)
            self.save_operation(operation, collector_id, connection)
            connection.execute(
                "INSERT INTO jobs(operation_id, kind, payload, status, available_at) VALUES(?, ?, ?, 'queued', ?)",
                (operation_id, kind, json.dumps(job_payload, ensure_ascii=False), utc_now()),
            )
        return operation

    def claim_job(self, lease_seconds: int) -> dict[str, Any] | None:
        now = utc_now()
        lease_until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE available_at <= ? AND (status='queued' OR (status='processing' AND lease_until < ?))
                ORDER BY id LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if not row:
                return None
            connection.execute(
                "UPDATE jobs SET status='processing', attempts=attempts+1, lease_until=? WHERE id=?",
                (lease_until, row["id"]),
            )
            return {
                "id": row["id"],
                "operationId": row["operation_id"],
                "kind": row["kind"],
                "payload": json.loads(row["payload"]),
                "attempts": row["attempts"] + 1,
            }

    def finish_job(self, job_id: int) -> None:
        with self.transaction() as connection:
            connection.execute("UPDATE jobs SET status='completed', lease_until=NULL WHERE id=?", (job_id,))

    def fail_job(self, job_id: int, message: str) -> None:
        with self.transaction() as connection:
            connection.execute("UPDATE jobs SET status='failed', lease_until=NULL, last_error=? WHERE id=?", (message[:2000], job_id))

    def list_runs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data, created_at FROM runs ORDER BY created_at DESC").fetchall()
        return [run for row in rows if (run := self._decode_run(row)) is not None]

    def get_run(self, run_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode_run(connection.execute("SELECT data, created_at FROM runs WHERE id=?", (run_id,)).fetchone())
        with self.connect() as own:
            return self._decode_run(own.execute("SELECT data, created_at FROM runs WHERE id=?", (run_id,)).fetchone())

    def save_run(self, run: dict[str, Any], connection: sqlite3.Connection | None = None) -> None:
        now = utc_now()
        sql = """
            INSERT INTO runs(id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (run["id"], run["collectorId"], json.dumps(run, ensure_ascii=False), now, now)
        if connection is not None:
            connection.execute(sql, params)
            return
        with self.transaction() as own:
            own.execute(sql, params)

    def save_items(self, run_id: str, items: list[dict[str, Any]], connection: sqlite3.Connection | None = None) -> None:
        own_connection = connection is None
        target = connection or self.connect()
        try:
            if own_connection:
                target.execute("BEGIN IMMEDIATE")
            target.execute("DELETE FROM items WHERE run_id=?", (run_id,))
            for item in items:
                target.execute(
                    "INSERT INTO items(id, run_id, data, created_at) VALUES(?, ?, ?, ?)",
                    (item["id"], run_id, json.dumps(item, ensure_ascii=False), utc_now()),
                )
            if own_connection:
                target.commit()
        except Exception:
            if own_connection:
                target.rollback()
            raise
        finally:
            if own_connection:
                target.close()

    def list_items(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM items ORDER BY created_at DESC").fetchall()
        return [json.loads(row["data"]) for row in rows]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._decode(connection.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone())

    def has_active_run(self, collector_id: str, connection: sqlite3.Connection | None = None) -> bool:
        query = "SELECT data FROM runs WHERE collector_id=?"
        target = connection or self.connect()
        try:
            rows = target.execute(query, (collector_id,)).fetchall()
            return any(json.loads(row["data"])["status"] in NONTERMINAL_RUN_STATUSES for row in rows)
        finally:
            if connection is None:
                target.close()

    def ensure_signing_key(self, signing_key: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT data FROM signing_keys WHERE id=?", (signing_key["id"],)).fetchone()
            if row:
                existing = json.loads(row["data"])
                if existing["tenantId"] != signing_key["tenantId"] or existing["publicKeyPem"] != signing_key["publicKeyPem"]:
                    raise ValueError("signing key identity cannot be rebound")
                return existing
            now = utc_now()
            connection.execute(
                "INSERT INTO signing_keys(id, tenant_id, status, revision, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    signing_key["id"],
                    signing_key["tenantId"],
                    signing_key["status"],
                    signing_key["revision"],
                    json.dumps(signing_key, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return signing_key

    def get_signing_key(self, key_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM signing_keys WHERE id=?", (key_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM signing_keys WHERE id=?", (key_id,)).fetchone())

    def update_signing_key_status(
        self,
        key_id: str,
        status: str,
        *,
        actor_id: str,
        request_id: str,
        compromise_effective_at: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"trusted", "retired", "compromised"}:
            raise ValueError("unsupported signing key status")
        with self.transaction() as connection:
            signing_key = self.get_signing_key(key_id, connection)
            if signing_key is None:
                raise KeyError(key_id)
            allowed_transitions = {
                "pending": {"trusted", "compromised"},
                "trusted": {"retired", "compromised"},
                "retired": {"compromised"},
                "compromised": set(),
            }
            if status not in allowed_transitions.get(signing_key["status"], set()):
                raise ValueError(f"invalid signing key transition: {signing_key['status']} -> {status}")
            before_digest = f"sha256:{payload_hash(signing_key)}"
            signing_key["status"] = status
            signing_key["revision"] = int(signing_key["revision"]) + 1
            changed_at = utc_now()
            if status == "retired":
                signing_key["retiredAt"] = changed_at
            elif status == "compromised":
                signing_key["compromiseEffectiveAt"] = compromise_effective_at or changed_at
            connection.execute(
                "UPDATE signing_keys SET status=?, revision=?, data=?, updated_at=? WHERE id=?",
                (status, signing_key["revision"], json.dumps(signing_key, ensure_ascii=False), changed_at, key_id),
            )
            self._append_audit_event(
                connection,
                tenant_id=signing_key["tenantId"],
                target_type="SigningKey",
                target_id=key_id,
                audit={"actorId": actor_id, "action": f"signing_key.{status}", "requestId": request_id},
                before_digest=before_digest,
                after_digest=f"sha256:{payload_hash(signing_key)}",
            )
            return signing_key

    def get_rule_version(self, rule_version_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM rule_versions WHERE id=?", (rule_version_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM rule_versions WHERE id=?", (rule_version_id,)).fetchone())

    def get_rule_attestation(self, attestation_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM rule_attestations WHERE id=?", (attestation_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM rule_attestations WHERE id=?", (attestation_id,)).fetchone())

    def latest_rule_attestation(self, rule_version_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        query = "SELECT data FROM rule_attestations WHERE rule_version_id=? ORDER BY created_at DESC LIMIT 1"
        if connection is not None:
            return self._decode(connection.execute(query, (rule_version_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute(query, (rule_version_id,)).fetchone())

    def _append_audit_event(
        self,
        connection: sqlite3.Connection,
        *,
        tenant_id: str,
        target_type: str,
        target_id: str,
        audit: dict[str, Any],
        before_digest: str | None,
        after_digest: str | None,
    ) -> dict[str, Any]:
        previous_row = connection.execute(
            "SELECT id, event_hash FROM audit_events WHERE tenant_id=? ORDER BY sequence DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
        event = {
            "id": stable_id("audit", uuid.uuid4().hex),
            "tenantId": tenant_id,
            "actorId": audit["actorId"],
            "action": audit["action"],
            "targetType": target_type,
            "targetId": target_id,
            "beforeDigest": before_digest,
            "afterDigest": after_digest,
            "requestId": audit["requestId"],
            "occurredAt": utc_now(),
            "previousEventId": str(previous_row["id"]) if previous_row else None,
            "details": audit.get("details", {}),
        }
        event_hash = f"sha256:{payload_hash({'event': event, 'previousEventHash': previous_row['event_hash'] if previous_row else None})}"
        event["eventHash"] = event_hash
        connection.execute(
            "INSERT INTO audit_events(id, tenant_id, event_hash, data, created_at) VALUES(?, ?, ?, ?, ?)",
            (event["id"], tenant_id, event_hash, json.dumps(event, ensure_ascii=False), event["occurredAt"]),
        )
        return event

    def publish_rule_bundle(
        self,
        *,
        collector_id: str,
        rule_version: dict[str, Any],
        attestation: dict[str, Any],
        collector_changes: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            collector = self.get_collector(collector_id, connection)
            if collector is None:
                raise KeyError(collector_id)
            if self.get_rule_version(rule_version["id"], connection) is not None:
                raise ValueError("rule version already exists and is immutable")
            connection.execute(
                "INSERT INTO rule_versions(id, tenant_id, collector_id, rule_digest, data, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    rule_version["id"],
                    rule_version["tenantId"],
                    collector_id,
                    rule_version["ruleDigest"],
                    json.dumps(rule_version, ensure_ascii=False),
                    rule_version["createdAt"],
                ),
            )
            connection.execute(
                """
                INSERT INTO rule_attestations(
                    id, tenant_id, rule_version_id, rule_digest, key_id, data, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attestation["attestationId"],
                    attestation["tenantId"],
                    attestation["ruleVersionId"],
                    attestation["ruleDigest"],
                    attestation["keyId"],
                    json.dumps(attestation, ensure_ascii=False),
                    attestation["signedAt"],
                ),
            )
            self._append_audit_event(
                connection,
                tenant_id=rule_version["tenantId"],
                target_type="RuleVersion",
                target_id=rule_version["id"],
                audit=audit,
                before_digest=collector.get("candidate", {}).get("digest") if collector.get("candidate") else None,
                after_digest=rule_version["ruleDigest"],
            )
            collector.update(collector_changes)
            self.save_collector(collector, connection)
            return collector

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM audit_events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def verify_audit_chain(self, tenant_id: str) -> bool:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, event_hash, data FROM audit_events WHERE tenant_id=? ORDER BY sequence",
                (tenant_id,),
            ).fetchall()
        previous_event_id: str | None = None
        previous_event_hash: str | None = None
        for row in rows:
            event = json.loads(row["data"])
            recorded_hash = event.pop("eventHash", None)
            expected_hash = f"sha256:{payload_hash({'event': event, 'previousEventHash': previous_event_hash})}"
            if recorded_hash != expected_hash or row["event_hash"] != expected_hash or event["previousEventId"] != previous_event_id:
                return False
            previous_event_id = str(row["id"])
            previous_event_hash = expected_hash
        return True

    def idempotency_replay(self, scope: str, key: str, request: Any) -> tuple[int, dict[str, Any]] | None:
        digest = payload_hash(request)
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM idempotency WHERE scope=? AND key=?", (scope, key)).fetchone()
        if not row:
            return None
        if row["request_hash"] != digest:
            raise IdempotencyConflict(key)
        return int(row["status_code"]), json.loads(row["response"])

    def remember_idempotency(self, scope: str, key: str, request: Any, status_code: int, response: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO idempotency(scope, key, request_hash, status_code, response, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (scope, key, payload_hash(request), status_code, json.dumps(response, ensure_ascii=False), utc_now()),
            )
