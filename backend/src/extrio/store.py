import base64
import hashlib
import json
import re
import threading
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

from extrio.config import get_settings
from extrio.credentials import CredentialCipher
from extrio.store_dialect import MIGRATION_ID_PATTERN, DialectConnection, resolve_database

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
SINK_TYPES = ("webhook",)
DELIVERY_STATUSES = ("pending", "delivering", "delivered", "failed", "dead_lettered")
EXPORT_ITEMS_CAP = 100_000


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


def encode_item_cursor(observed_at: str, entity_key: str, item_id: str) -> str:
    payload = json.dumps([observed_at, entity_key, item_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_item_cursor(cursor: str) -> tuple[str, str, str]:
    try:
        payload = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor("item pagination cursor is invalid") from exc
    if not isinstance(payload, list) or len(payload) != 3 or not all(isinstance(part, str) for part in payload):
        raise InvalidCursor("item pagination cursor is invalid")
    return payload[0], payload[1], payload[2]


class IdempotencyConflict(Exception):
    pass


class AuthSetupComplete(Exception):
    pass


class UsernameTaken(Exception):
    """Raised when a new username collides case-insensitively with an existing account."""

    code = "USERNAME_TAKEN"


class InvalidCursor(Exception):
    """Raised when a pagination cursor cannot be decoded or validated."""

    code = "INVALID_CURSOR"


class Store:
    def __init__(self, path: Path, *, database_url: str | None = None):
        self._init_lock = threading.Lock()
        effective_url = database_url if database_url is not None else get_settings().database_url
        self.dialect, sqlite_path = resolve_database(effective_url, path)
        self.database_url = effective_url or None
        self.path = sqlite_path

    def connect(self) -> DialectConnection:
        return self.dialect.connect(self.database_url, self.path)

    def transaction(self) -> AbstractContextManager[DialectConnection]:
        return self.dialect.transaction(self.database_url, self.path)

    def initialize(self) -> None:
        with self._init_lock:
            if self.dialect.name == "sqlite":
                self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as connection:
                self._run_migrations(connection)
            if self.dialect.name == "sqlite":
                with self.connect() as connection:
                    self._backfill_ai_runs(connection)

    def _migration_dir(self) -> Path:
        packaged = Path(__file__).resolve().parent / "migrations"
        if packaged.is_dir():
            return packaged
        repository = Path(__file__).resolve().parents[2] / "migrations"
        if repository.is_dir():
            return repository
        raise RuntimeError("extrio database migrations directory was not found")

    def _run_migrations(self, connection: DialectConnection) -> None:
        suffix = ".sqlite.sql" if self.dialect.name == "sqlite" else ".pg.sql"
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {str(row["id"]) for row in connection.execute("SELECT id FROM schema_migrations").fetchall()}
        for file_path in sorted(self._migration_dir().glob(f"*{suffix}")):
            migration_id = file_path.name.removesuffix(suffix)
            if not MIGRATION_ID_PATTERN.fullmatch(migration_id):
                raise RuntimeError(f"migration id {migration_id!r} is invalid")
            if migration_id in applied:
                continue
            record = f"INSERT INTO schema_migrations(id, applied_at) VALUES('{migration_id}', '{utc_now()}');"
            try:
                self.dialect.run_script(connection, f"{file_path.read_text(encoding='utf-8')}\n{record}")
            except Exception as exc:
                raise RuntimeError(f"database migration {migration_id!r} failed: {exc}") from exc

    def _backfill_ai_runs(self, connection: DialectConnection) -> None:
        rows = connection.execute(
            """
            SELECT operations.id AS operation_id, operations.collector_id, operations.data AS operation_data,
                   operations.created_at, operations.updated_at, collectors.data AS collector_data,
                   jobs.payload AS job_payload
            FROM operations
            JOIN collectors ON collectors.id = operations.collector_id
            LEFT JOIN ai_runs ON ai_runs.operation_id = operations.id
            LEFT JOIN jobs ON jobs.operation_id = operations.id
            WHERE ai_runs.id IS NULL
            ORDER BY operations.created_at DESC
            """
        ).fetchall()
        seen_collectors: set[str] = set()
        for row in rows:
            operation = self.dialect.decode_json(row["operation_data"])
            if operation.get("kind") != "explore":
                continue
            collector = self.dialect.decode_json(row["collector_data"])
            status = operation.get("status", "queued")
            terminal = status in TERMINAL_OPERATION_STATUSES
            is_latest = str(row["collector_id"]) not in seen_collectors
            seen_collectors.add(str(row["collector_id"]))
            has_candidate = bool(collector.get("candidate"))
            if status == "succeeded":
                result_status = "candidate_ready" if has_candidate or not is_latest else "no_candidate"
                if not is_latest:
                    review_status = "superseded"
                elif collector.get("status") == "published":
                    review_status = "published"
                elif collector.get("status") == "ready_review" and has_candidate:
                    review_status = "ready_review"
                else:
                    review_status = "superseded"
            elif terminal:
                result_status = "no_candidate"
                review_status = "not_ready"
            else:
                result_status = "pending"
                review_status = "not_ready"
            created_at = str(row["created_at"])
            updated_at = str(row["updated_at"])
            duration_ms = None
            if terminal:
                started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                finished = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                duration_ms = max(0, int((finished - started).total_seconds() * 1000))
            ai_run_id = stable_id("ai_run", str(row["operation_id"]), 120)
            metrics = operation.get("metrics") or {}
            ai_run = {
                "id": ai_run_id,
                "operationId": row["operation_id"],
                "collectorId": row["collector_id"],
                "collectorName": collector.get("name", row["collector_id"]),
                "sourceUrl": collector.get("sourceUrl", ""),
                "kind": "rule_repair" if collector.get("activeRuleVersion") else "rule_generation",
                "trigger": "regeneration" if collector.get("activeRuleVersion") or collector.get("candidate") else "initial_generation",
                "initiatedBy": "system:migration",
                "status": status,
                "phase": operation.get("phase", "queued"),
                "progress": operation.get("progress", 0),
                "resultStatus": result_status,
                "reviewStatus": review_status,
                "attemptCount": 0,
                "modelSummary": {"invocationCount": 0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "estimatedCost": None},
                "validationSummary": {"acceptedSamples": 0, "rejectedSamples": 0, "warningCount": int(metrics.get("warningCount", 0))},
                "candidateRuleDigest": collector.get("candidate", {}).get("digest") if is_latest and has_candidate else None,
                "publishedRuleVersionId": collector.get("activeRuleVersion") if review_status == "published" else None,
                "createdAt": created_at,
                "startedAt": created_at if status != "queued" else None,
                "finishedAt": updated_at if terminal else None,
                "durationMs": duration_ms,
                "error": operation.get("error"),
            }
            connection.execute(
                self.dialect.insert_or_ignore(
                    "INSERT INTO ai_runs(id, operation_id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)"
                ),
                (
                    ai_run_id,
                    row["operation_id"],
                    row["collector_id"],
                    self.dialect.json_param(ai_run),
                    created_at,
                    updated_at,
                ),
            )
            if row["job_payload"]:
                payload = self.dialect.decode_json(row["job_payload"])
                if not payload.get("aiRunId"):
                    payload["aiRunId"] = ai_run_id
                    connection.execute(
                        "UPDATE jobs SET payload=? WHERE operation_id=?",
                        (self.dialect.json_param(payload), row["operation_id"]),
                    )

    @staticmethod
    def _auth_user(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "role": row["role"],
            "enabled": bool(row["enabled"]),
        }

    @staticmethod
    def _user_view(row: Any) -> dict[str, Any] | None:
        user = Store._auth_user(row)
        if user is None:
            return None
        user["createdAt"] = row["created_at"]
        user["updatedAt"] = row["updated_at"]
        return user

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
                f"SELECT * FROM auth_users WHERE {self.dialect.nocase_equality('username')}",
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

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        role: str,
        display_name: str,
    ) -> dict[str, Any]:
        """Create a team account; duplicate usernames are rejected case-insensitively."""

        now = utc_now()
        user_id = stable_id("user", uuid.uuid4().hex, 32)
        with self.transaction() as connection:
            if connection.execute(
                f"SELECT 1 FROM auth_users WHERE {self.dialect.nocase_equality('username')}",
                (username,),
            ).fetchone() is not None:
                raise UsernameTaken(username)
            connection.execute(
                """
                INSERT INTO auth_users(id, username, password_hash, role, display_name, enabled, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, role, display_name, self.dialect.bool_param(True), now, now),
            )
            row = connection.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
        user = self._user_view(row)
        if user is None:
            raise RuntimeError("created authentication user is unavailable")
        return user

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
        return self._user_view(row)

    def list_users(self) -> list[dict[str, Any]]:
        """List account views ordered by creation; password hashes never leave the store."""

        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM auth_users ORDER BY created_at, id").fetchall()
        return [view for row in rows if (view := self._user_view(row)) is not None]

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        display_name: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Partially update an account; raises KeyError when the user does not exist."""

        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise KeyError(user_id)
            assignments: list[str] = []
            params: list[Any] = []
            if role is not None:
                assignments.append("role=?")
                params.append(role)
            if display_name is not None:
                assignments.append("display_name=?")
                params.append(display_name)
            if enabled is not None:
                assignments.append("enabled=?")
                params.append(self.dialect.bool_param(enabled))
            if assignments:
                assignments.append("updated_at=?")
                params.extend((utc_now(), user_id))
                connection.execute(f"UPDATE auth_users SET {', '.join(assignments)} WHERE id=?", tuple(params))
            updated = connection.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
        view = self._user_view(updated)
        if view is None:
            raise KeyError(user_id)
        return view

    def update_user_password(self, user_id: str, password_hash: str) -> None:
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM auth_users WHERE id=?", (user_id,)).fetchone() is None:
                raise KeyError(user_id)
            connection.execute(
                "UPDATE auth_users SET password_hash=?, updated_at=? WHERE id=?",
                (password_hash, utc_now(), user_id),
            )

    def count_active_administrators(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM auth_users WHERE role='administrator' AND enabled={self.dialect.bool_true()}"
            ).fetchone()
        return int(row["total"])

    def get_platform_setting(self, key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT data FROM platform_settings WHERE key=?", (key,)).fetchone()
        return self._decode(row)

    def save_platform_setting(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        payload = {**value, "updatedAt": now}
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO platform_settings(key, data, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (key, self.dialect.json_param(payload), now),
            )
        return payload

    def _decode(self, row: Any) -> dict[str, Any] | None:
        return self.dialect.decode_json(row["data"]) if row else None

    def _decode_run(self, row: Any) -> dict[str, Any] | None:
        if not row:
            return None
        run = self.dialect.decode_json(row["data"])
        run["startedAtIso"] = row["created_at"]
        return run

    def list_collectors(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM collectors ORDER BY created_at DESC").fetchall()
        return [self.dialect.decode_json(row["data"]) for row in rows]

    def get_collector(self, collector_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM collectors WHERE id=?", (collector_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM collectors WHERE id=?", (collector_id,)).fetchone())

    def save_collector(self, collector: dict[str, Any], connection: DialectConnection | None = None) -> None:
        now = utc_now()
        sql = """
            INSERT INTO collectors(id, data, created_at, updated_at) VALUES(?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (collector["id"], self.dialect.json_param(collector), now, now)
        if connection is not None:
            connection.execute(sql, params)
            return
        with self.transaction() as own:
            own.execute(sql, params)

    def source_exists(
        self,
        source_url: str,
        connection: DialectConnection | None = None,
        *,
        exclude_collector_id: str | None = None,
    ) -> bool:
        source_url_expression = self.dialect.json_extract_text("data", "sourceUrl")
        query = f"SELECT 1 FROM collectors WHERE {source_url_expression}=?"
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
                (policy_id, collector_id, version, policy["digest"], self.dialect.json_param(policy), created_at),
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

    def get_collection_policy(self, policy_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        query = "SELECT data FROM collection_policies WHERE id=?"
        if connection is not None:
            return self._decode(connection.execute(query, (policy_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute(query, (policy_id,)).fetchone())

    def get_checkpoint(self, collector_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
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
                    self.dialect.bool_param(schedule["enabled"]),
                    schedule["nextRunAt"],
                    schedule["lastTriggeredAt"],
                    self.dialect.json_param(schedule),
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
                f"SELECT data FROM collector_schedules WHERE enabled={self.dialect.bool_true()} "
                "AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at",
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
                    self.dialect.insert_or_ignore(
                        """
                        INSERT INTO schedule_occurrences(
                            occurrence_key, schedule_id, collector_id, scheduled_at, status, run_id, reason, data, created_at, updated_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                    ),
                    (
                        occurrence_key,
                        schedule["id"],
                        schedule["collectorId"],
                        scheduled_at,
                        "claimed",
                        None,
                        None,
                        self.dialect.json_param(occurrence),
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
                    (next_run_at, scheduled_at, self.dialect.json_param(schedule), created_at, schedule["id"]),
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
                (status, run_id, reason, self.dialect.json_param(occurrence), utc_now(), occurrence_key),
            )

    def save_checkpoint(self, checkpoint: dict[str, Any], connection: DialectConnection | None = None) -> None:
        if connection is not None:
            self._write_checkpoint(connection, checkpoint)
            return
        with self.transaction() as target:
            self._write_checkpoint(target, checkpoint)

    def _write_checkpoint(self, connection: DialectConnection, checkpoint: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO collector_checkpoints(collector_id, policy_version_id, data, updated_at) VALUES(?, ?, ?, ?)
            ON CONFLICT(collector_id) DO UPDATE SET
                policy_version_id=excluded.policy_version_id, data=excluded.data, updated_at=excluded.updated_at
            """,
            (checkpoint["collectorId"], checkpoint["policyVersionId"], self.dialect.json_param(checkpoint), utc_now()),
        )
        collector = self.get_collector(checkpoint["collectorId"], connection)
        if collector is None:
            raise KeyError(checkpoint["collectorId"])
        collector["checkpoint"] = checkpoint
        self.save_collector(collector, connection)

    def get_operation(self, operation_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM operations WHERE id=?", (operation_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM operations WHERE id=?", (operation_id,)).fetchone())

    def list_operations(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM operations ORDER BY created_at DESC").fetchall()
        return [self.dialect.decode_json(row["data"]) for row in rows]

    def list_ai_runs(self, collector_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if collector_id:
                rows = connection.execute(
                    "SELECT data FROM ai_runs WHERE collector_id=? ORDER BY created_at DESC",
                    (collector_id,),
                ).fetchall()
            else:
                rows = connection.execute("SELECT data FROM ai_runs ORDER BY created_at DESC").fetchall()
        return [{"publishedRuleVersionId": None, **self.dialect.decode_json(row["data"])} for row in rows]

    def get_ai_run(self, ai_run_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            ai_run = self._decode(connection.execute("SELECT data FROM ai_runs WHERE id=?", (ai_run_id,)).fetchone())
            if ai_run is None:
                return None
            return {"publishedRuleVersionId": None, **ai_run, "attempts": self.list_ai_attempts(ai_run_id, connection)}
        with self.connect() as own:
            ai_run = self._decode(own.execute("SELECT data FROM ai_runs WHERE id=?", (ai_run_id,)).fetchone())
            if ai_run is None:
                return None
            return {"publishedRuleVersionId": None, **ai_run, "attempts": self.list_ai_attempts(ai_run_id, own)}

    def save_ai_run(
        self,
        ai_run: dict[str, Any],
        collector_id: str,
        operation_id: str,
        connection: DialectConnection | None = None,
    ) -> None:
        now = utc_now()
        sql = """
            INSERT INTO ai_runs(id, operation_id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (ai_run["id"], operation_id, collector_id, self.dialect.json_param(ai_run), now, now)
        if connection is not None:
            connection.execute(sql, params)
            return
        with self.transaction() as own:
            own.execute(sql, params)

    def update_ai_run(self, ai_run_id: str, **changes: Any) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT operation_id, collector_id, data FROM ai_runs WHERE id=?",
                (ai_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(ai_run_id)
            ai_run = self.dialect.decode_json(row["data"])
            ai_run.update(changes)
            if changes.get("reviewStatus") == "ready_review":
                older_rows = connection.execute(
                    "SELECT operation_id, data FROM ai_runs WHERE collector_id=? AND id<>?",
                    (row["collector_id"], ai_run_id),
                ).fetchall()
                for older_row in older_rows:
                    older_ai_run = self.dialect.decode_json(older_row["data"])
                    if older_ai_run.get("reviewStatus") != "ready_review":
                        continue
                    older_ai_run.update(reviewStatus="superseded", publishedRuleVersionId=None)
                    self.save_ai_run(
                        older_ai_run,
                        str(row["collector_id"]),
                        str(older_row["operation_id"]),
                        connection,
                    )
            self.save_ai_run(ai_run, str(row["collector_id"]), str(row["operation_id"]), connection)
            return ai_run

    def mark_latest_ai_run_published(
        self,
        collector_id: str,
        rule_version_id: str,
        connection: DialectConnection | None = None,
    ) -> None:
        if connection is not None:
            self._publish_latest_ai_run(connection, collector_id, rule_version_id)
            return
        with self.transaction() as target:
            self._publish_latest_ai_run(target, collector_id, rule_version_id)

    def _publish_latest_ai_run(self, connection: DialectConnection, collector_id: str, rule_version_id: str) -> None:
        rows = connection.execute(
            "SELECT operation_id, data FROM ai_runs WHERE collector_id=? ORDER BY created_at DESC",
            (collector_id,),
        ).fetchall()
        published = False
        for row in rows:
            ai_run = self.dialect.decode_json(row["data"])
            if ai_run.get("reviewStatus") != "ready_review":
                continue
            if not published:
                ai_run.update(reviewStatus="published", publishedRuleVersionId=rule_version_id)
                published = True
            else:
                ai_run.update(reviewStatus="superseded", publishedRuleVersionId=None)
            self.save_ai_run(ai_run, collector_id, str(row["operation_id"]), connection)

    def list_ai_attempts(
        self,
        ai_run_id: str,
        connection: DialectConnection | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT data FROM ai_attempts WHERE ai_run_id=? ORDER BY attempt_no DESC"
        if connection is not None:
            rows = connection.execute(query, (ai_run_id,)).fetchall()
            attempts = [self.dialect.decode_json(row["data"]) for row in rows]
            return [{**attempt, "modelInvocations": self.list_model_invocations(attempt["id"], connection)} for attempt in attempts]
        with self.connect() as own:
            rows = own.execute(query, (ai_run_id,)).fetchall()
            attempts = [self.dialect.decode_json(row["data"]) for row in rows]
            return [{**attempt, "modelInvocations": self.list_model_invocations(attempt["id"], own)} for attempt in attempts]

    def start_ai_attempt(self, ai_run_id: str) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT operation_id, collector_id, data FROM ai_runs WHERE id=?",
                (ai_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(ai_run_id)
            attempt_row = connection.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) AS attempt_no FROM ai_attempts WHERE ai_run_id=?",
                (ai_run_id,),
            ).fetchone()
            attempt_no = int(attempt_row["attempt_no"]) + 1
            now = utc_now()
            attempt = {
                "id": stable_id("ai_attempt", f"{ai_run_id}_{attempt_no}", 120),
                "aiRunId": ai_run_id,
                "attemptNo": attempt_no,
                "status": "running",
                "startedAt": now,
                "finishedAt": None,
                "durationMs": None,
                "error": None,
            }
            connection.execute(
                "INSERT INTO ai_attempts(id, ai_run_id, attempt_no, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (attempt["id"], ai_run_id, attempt_no, self.dialect.json_param(attempt), now, now),
            )
            ai_run = self.dialect.decode_json(row["data"])
            ai_run.update(status="running", startedAt=ai_run.get("startedAt") or now, attemptCount=attempt_no)
            self.save_ai_run(ai_run, str(row["collector_id"]), str(row["operation_id"]), connection)
            return attempt

    def finish_ai_attempt(self, attempt_id: str, *, status: str, error: dict[str, Any] | None) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT data FROM ai_attempts WHERE id=?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            attempt = self.dialect.decode_json(row["data"])
            finished_at = utc_now()
            started_at = datetime.fromisoformat(attempt["startedAt"].replace("Z", "+00:00"))
            finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            attempt.update(
                status=status,
                finishedAt=finished_at,
                durationMs=max(0, int((finished - started_at).total_seconds() * 1000)),
                error=error,
            )
            connection.execute(
                "UPDATE ai_attempts SET data=?, updated_at=? WHERE id=?",
                (self.dialect.json_param(attempt), finished_at, attempt_id),
            )
            return attempt

    def list_model_invocations(
        self,
        attempt_id: str,
        connection: DialectConnection | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT data FROM model_invocations WHERE ai_attempt_id=? ORDER BY created_at"
        if connection is not None:
            rows = connection.execute(query, (attempt_id,)).fetchall()
            return [self.dialect.decode_json(row["data"]) for row in rows]
        with self.connect() as own:
            rows = own.execute(query, (attempt_id,)).fetchall()
            return [self.dialect.decode_json(row["data"]) for row in rows]

    def record_model_invocation(
        self,
        *,
        ai_run_id: str,
        attempt_id: str,
        purpose: str,
        provider: str,
        model: str,
        prompt_version: str,
        status: str,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        response_digest: str | None,
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        invocation = {
            "id": stable_id("model_call", uuid.uuid4().hex, 32),
            "aiRunId": ai_run_id,
            "aiAttemptId": attempt_id,
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "promptVersion": prompt_version,
            "status": status,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "durationMs": duration_ms,
            "promptTokens": max(0, prompt_tokens),
            "completionTokens": max(0, completion_tokens),
            "totalTokens": max(0, prompt_tokens) + max(0, completion_tokens),
            "estimatedCost": None,
            "responseDigest": response_digest,
            "error": error,
        }
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO model_invocations(id, ai_run_id, ai_attempt_id, data, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (invocation["id"], ai_run_id, attempt_id, self.dialect.json_param(invocation), started_at, finished_at),
            )
            row = connection.execute(
                "SELECT operation_id, collector_id, data FROM ai_runs WHERE id=?",
                (ai_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(ai_run_id)
            ai_run = self.dialect.decode_json(row["data"])
            summary = dict(ai_run.get("modelSummary") or {})
            summary.update(
                invocationCount=int(summary.get("invocationCount", 0)) + 1,
                promptTokens=int(summary.get("promptTokens", 0)) + invocation["promptTokens"],
                completionTokens=int(summary.get("completionTokens", 0)) + invocation["completionTokens"],
                totalTokens=int(summary.get("totalTokens", 0)) + invocation["totalTokens"],
                estimatedCost=None,
            )
            ai_run["modelSummary"] = summary
            self.save_ai_run(ai_run, str(row["collector_id"]), str(row["operation_id"]), connection)
        return invocation

    def save_operation(self, operation: dict[str, Any], collector_id: str, connection: DialectConnection | None = None) -> None:
        now = utc_now()
        sql = """
            INSERT INTO operations(id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (operation["id"], collector_id, self.dialect.json_param(operation), now, now)
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
    def operation_collector_id(operation_id: str, connection: DialectConnection) -> str:
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
        ai_run: dict[str, Any] | None = None,
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
            if ai_run is not None:
                now = utc_now()
                ai_run = {
                    **ai_run,
                    "operationId": operation_id,
                    "status": "queued",
                    "phase": "queued",
                    "progress": 0,
                    "resultStatus": "pending",
                    "reviewStatus": "not_ready",
                    "attemptCount": 0,
                    "modelSummary": {
                        "invocationCount": 0,
                        "promptTokens": 0,
                        "completionTokens": 0,
                        "totalTokens": 0,
                        "estimatedCost": None,
                    },
                    "validationSummary": {"acceptedSamples": 0, "rejectedSamples": 0, "warningCount": 0},
                    "candidateRuleDigest": None,
                    "publishedRuleVersionId": None,
                    "createdAt": now,
                    "startedAt": None,
                    "finishedAt": None,
                    "durationMs": None,
                    "error": None,
                }
                self.save_ai_run(ai_run, collector_id, operation_id, connection)
            connection.execute(
                "INSERT INTO jobs(operation_id, kind, payload, status, available_at) VALUES(?, ?, ?, 'queued', ?)",
                (operation_id, kind, self.dialect.json_param(job_payload), utc_now()),
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
                "payload": self.dialect.decode_json(row["payload"]),
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

    def get_run(self, run_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode_run(connection.execute("SELECT data, created_at FROM runs WHERE id=?", (run_id,)).fetchone())
        with self.connect() as own:
            return self._decode_run(own.execute("SELECT data, created_at FROM runs WHERE id=?", (run_id,)).fetchone())

    def save_run(self, run: dict[str, Any], connection: DialectConnection | None = None) -> None:
        now = utc_now()
        sql = """
            INSERT INTO runs(id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """
        params = (run["id"], run["collectorId"], self.dialect.json_param(run), now, now)
        if connection is not None:
            connection.execute(sql, params)
            return
        with self.transaction() as own:
            own.execute(sql, params)

    def save_items(self, run_id: str, items: list[dict[str, Any]], connection: DialectConnection | None = None) -> None:
        if connection is not None:
            self._replace_run_items(connection, run_id, items)
            return
        with self.transaction() as target:
            self._replace_run_items(target, run_id, items)

    def _replace_run_items(self, connection: DialectConnection, run_id: str, items: list[dict[str, Any]]) -> None:
        connection.execute("DELETE FROM items WHERE run_id=?", (run_id,))
        for item in items:
            connection.execute(
                "INSERT INTO items(id, run_id, data, created_at) VALUES(?, ?, ?, ?)",
                (item["id"], run_id, self.dialect.json_param(item), utc_now()),
            )

    def list_items(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM items ORDER BY created_at DESC").fetchall()
        return [self.dialect.decode_json(row["data"]) for row in rows]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._decode(connection.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone())

    def _item_filter_clauses(
        self,
        *,
        collector_id: str | None,
        run_id: str | None,
        decision: str | None,
        entity_key: str | None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if collector_id is not None:
            clauses.append(f"{self.dialect.json_extract_text('data', 'collectorId')}=?")
            params.append(collector_id)
        if run_id is not None:
            clauses.append("run_id=?")
            params.append(run_id)
        if decision is not None:
            clauses.append(f"{self.dialect.json_extract_text('data', 'decision')}=?")
            params.append(decision)
        if entity_key is not None:
            clauses.append(f"{self.dialect.json_extract_text('data', 'entityKey')}=?")
            params.append(entity_key)
        return clauses, params

    def list_items_cursor(
        self,
        *,
        collector_id: str | None = None,
        run_id: str | None = None,
        decision: str | None = None,
        entity_key: str | None = None,
        sort_key: str = "observed_at",
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Page items in the deterministic output-loop order.

        Ordering contract: ``(observedAt DESC, entityKey DESC)`` with the item
        id as a final tiebreaker, so equal sort keys never reorder between
        pages. The returned ``nextCursor`` is an opaque base64 token carrying
        the last sort key tuple ``(observedAt, entityKey, id)``; decoding it is
        the only way to resume a page walk and an invalid token raises
        :class:`InvalidCursor` (error code ``INVALID_CURSOR``). Items always
        carry non-null ``observedAt``/``entityKey`` fields, which holds for
        every item produced by the harvest pipeline.
        """

        if sort_key != "observed_at":
            raise ValueError("only the observed_at sort key is supported")
        if limit < 1:
            raise ValueError("limit must be positive")
        observed_at = self.dialect.json_extract_text("data", "observedAt")
        entity_key_expression = self.dialect.json_extract_text("data", "entityKey")
        clauses, params = self._item_filter_clauses(
            collector_id=collector_id,
            run_id=run_id,
            decision=decision,
            entity_key=entity_key,
        )
        if cursor is not None:
            cursor_observed_at, cursor_entity_key, cursor_item_id = decode_item_cursor(cursor)
            clauses.append(f"({observed_at}, {entity_key_expression}, id) < (?, ?, ?)")
            params.extend((cursor_observed_at, cursor_entity_key, cursor_item_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT data FROM items {where} "
                f"ORDER BY {observed_at} DESC, {entity_key_expression} DESC, id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        items = [self.dialect.decode_json(row["data"]) for row in rows[:limit]]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_item_cursor(str(last["observedAt"]), str(last["entityKey"]), str(last["id"]))
        return {"items": items, "nextCursor": next_cursor}

    def iter_items_export(
        self,
        *,
        collector_id: str | None = None,
        run_id: str | None = None,
        decision: str | None = None,
        entity_key: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield items in the same deterministic order as ``list_items_cursor``.

        Iteration is unbounded by design: the export surface caps results at
        ``EXPORT_ITEMS_CAP`` items and that cap is enforced by the caller, so
        this generator only guarantees stable ordered streaming.
        """

        observed_at = self.dialect.json_extract_text("data", "observedAt")
        entity_key_expression = self.dialect.json_extract_text("data", "entityKey")
        clauses, params = self._item_filter_clauses(
            collector_id=collector_id,
            run_id=run_id,
            decision=decision,
            entity_key=entity_key,
        )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        connection = self.connect()
        try:
            cursor = connection.execute(
                f"SELECT data FROM items {where} ORDER BY {observed_at} DESC, {entity_key_expression} DESC, id DESC",
                tuple(params),
            )
            while batch := cursor.fetchmany(500):
                for row in batch:
                    yield self.dialect.decode_json(row["data"])
        finally:
            connection.close()

    def has_active_run(self, collector_id: str, connection: DialectConnection | None = None) -> bool:
        query = "SELECT data FROM runs WHERE collector_id=?"
        target = connection or self.connect()
        try:
            rows = target.execute(query, (collector_id,)).fetchall()
            return any(self.dialect.decode_json(row["data"])["status"] in NONTERMINAL_RUN_STATUSES for row in rows)
        finally:
            if connection is None:
                target.close()

    def ensure_signing_key(self, signing_key: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT data FROM signing_keys WHERE id=?", (signing_key["id"],)).fetchone()
            if row:
                existing = self.dialect.decode_json(row["data"])
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
                    self.dialect.json_param(signing_key),
                    now,
                    now,
                ),
            )
            return signing_key

    def get_signing_key(self, key_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
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
                (status, signing_key["revision"], self.dialect.json_param(signing_key), changed_at, key_id),
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

    def get_rule_version(self, rule_version_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM rule_versions WHERE id=?", (rule_version_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM rule_versions WHERE id=?", (rule_version_id,)).fetchone())

    def get_rule_attestation(self, attestation_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        if connection is not None:
            return self._decode(connection.execute("SELECT data FROM rule_attestations WHERE id=?", (attestation_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute("SELECT data FROM rule_attestations WHERE id=?", (attestation_id,)).fetchone())

    def latest_rule_attestation(self, rule_version_id: str, connection: DialectConnection | None = None) -> dict[str, Any] | None:
        query = "SELECT data FROM rule_attestations WHERE rule_version_id=? ORDER BY created_at DESC LIMIT 1"
        if connection is not None:
            return self._decode(connection.execute(query, (rule_version_id,)).fetchone())
        with self.connect() as own:
            return self._decode(own.execute(query, (rule_version_id,)).fetchone())

    def _append_audit_event(
        self,
        connection: DialectConnection,
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
            (event["id"], tenant_id, event_hash, self.dialect.json_param(event), event["occurredAt"]),
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
                    self.dialect.json_param(rule_version),
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
                    self.dialect.json_param(attestation),
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
            self.mark_latest_ai_run_published(collector_id, rule_version["id"], connection)
            return collector

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data FROM audit_events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return [self.dialect.decode_json(row["data"]) for row in rows]

    def verify_audit_chain(self, tenant_id: str) -> bool:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, event_hash, data FROM audit_events WHERE tenant_id=? ORDER BY sequence",
                (tenant_id,),
            ).fetchall()
        previous_event_id: str | None = None
        previous_event_hash: str | None = None
        for row in rows:
            event = self.dialect.decode_json(row["data"])
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
        return int(row["status_code"]), self.dialect.decode_json(row["response"])

    def remember_idempotency(self, scope: str, key: str, request: Any, status_code: int, response: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                self.dialect.insert_or_ignore(
                    "INSERT INTO idempotency(scope, key, request_hash, status_code, response, created_at) VALUES(?, ?, ?, ?, ?, ?)"
                ),
                (scope, key, payload_hash(request), status_code, self.dialect.json_param(response), utc_now()),
            )

    def create_sink(
        self,
        collector_id: str,
        *,
        cipher: CredentialCipher,
        url: str,
        secret: str | None = None,
        enabled: bool = True,
        sink_type: str = "webhook",
    ) -> dict[str, Any]:
        """Register an output sink for a collector; secrets are Fernet-encrypted."""

        if sink_type not in SINK_TYPES:
            raise ValueError(f"unsupported sink type: {sink_type!r}")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("sink url must be a non-empty string")
        now = utc_now()
        sink_id = stable_id("sink", f"{collector_id}_{uuid.uuid4().hex}", 40)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sinks(id, collector_id, type, url, secret_encrypted, enabled, version, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    sink_id,
                    collector_id,
                    sink_type,
                    url,
                    cipher.encrypt(secret) if secret else None,
                    self.dialect.bool_param(enabled),
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM sinks WHERE id=?", (sink_id,)).fetchone()
        return self._sink_view(row)

    def update_sink(
        self,
        sink_id: str,
        *,
        cipher: CredentialCipher | None = None,
        url: str | None = None,
        secret: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Update a sink; every update bumps its version."""

        if secret is not None and cipher is None:
            raise ValueError("updating the sink secret requires the credential cipher")
        if url is not None and (not isinstance(url, str) or not url.strip()):
            raise ValueError("sink url must be a non-empty string")
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM sinks WHERE id=?", (sink_id,)).fetchone()
            if row is None:
                raise KeyError(sink_id)
            connection.execute(
                "UPDATE sinks SET url=?, enabled=?, secret_encrypted=?, version=version+1, updated_at=? WHERE id=?",
                (
                    url if url is not None else row["url"],
                    self.dialect.bool_param(enabled) if enabled is not None else row["enabled"],
                    cipher.encrypt(secret) if secret is not None else row["secret_encrypted"],
                    utc_now(),
                    sink_id,
                ),
            )
            return self._sink_view(connection.execute("SELECT * FROM sinks WHERE id=?", (sink_id,)).fetchone())

    def get_sink(self, sink_id: str, *, cipher: CredentialCipher | None = None) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sinks WHERE id=?", (sink_id,)).fetchone()
        if row is None:
            return None
        view = self._sink_view(row)
        if cipher is not None and row["secret_encrypted"]:
            view["secret"] = cipher.decrypt(str(row["secret_encrypted"]))
        return view

    def list_sinks_for_collector(self, collector_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sinks WHERE collector_id=? ORDER BY created_at DESC, id DESC",
                (collector_id,),
            ).fetchall()
        return [self._sink_view(row) for row in rows]

    def delete_sink(self, sink_id: str) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT id FROM sinks WHERE id=?", (sink_id,)).fetchone()
            if row is None:
                raise KeyError(sink_id)
            connection.execute("DELETE FROM sinks WHERE id=?", (sink_id,))

    @staticmethod
    def _sink_view(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "collectorId": row["collector_id"],
            "type": row["type"],
            "url": row["url"],
            "enabled": bool(row["enabled"]),
            "version": int(row["version"]),
            "secretConfigured": bool(row["secret_encrypted"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def enqueue_delivery(
        self,
        *,
        collector_id: str,
        sink_id: str,
        item_event_id: str,
        sink_version_id: str | None = None,
    ) -> dict[str, Any]:
        """Idempotently enqueue an item event for a sink; duplicates return the same delivery."""

        now = utc_now()
        delivery_id = stable_id("delivery", uuid.uuid4().hex, 24)
        insert_sql = self.dialect.insert_or_ignore(
            """
            INSERT INTO deliveries(
                id, collector_id, sink_id, sink_version_id, item_event_id, status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """
        )
        with self.transaction() as connection:
            if sink_version_id is None:
                sink = connection.execute("SELECT id, version FROM sinks WHERE id=?", (sink_id,)).fetchone()
                if sink is None:
                    raise KeyError(sink_id)
                sink_version_id = f"{sink_id}#v{int(sink['version'])}"
            connection.execute(
                insert_sql,
                (delivery_id, collector_id, sink_id, sink_version_id, item_event_id, now, now, now),
            )
            row = connection.execute(
                "SELECT * FROM deliveries WHERE item_event_id=? AND sink_id=?",
                (item_event_id, sink_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("enqueued delivery is unavailable")
        return self._delivery_view(row)

    def claim_due_deliveries(
        self,
        limit: int,
        now: datetime | None = None,
        *,
        lease_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        """Lease due deliveries like ``claim_job`` leases jobs.

        A delivery is claimable when it is ``pending`` or ``failed`` with
        ``next_attempt_at`` due, or when it is stuck in ``delivering`` with an
        expired lease (a crashed dispatcher). Claimed rows move to
        ``delivering`` with a fresh lease. The claimed views include the
        joined sink target so a dispatcher can deliver without a second read.
        """

        if limit < 1:
            raise ValueError("claim limit must be positive")
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        now_iso = instant.isoformat().replace("+00:00", "Z")
        lease_until = (instant + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
        claimed: list[dict[str, Any]] = []
        with self.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, s.type AS sink_type, s.url AS sink_url, s.secret_encrypted AS sink_secret_encrypted
                FROM deliveries d
                JOIN sinks s ON s.id=d.sink_id
                WHERE (d.status IN ('pending', 'failed') AND d.next_attempt_at IS NOT NULL AND d.next_attempt_at<=?)
                   OR (d.status='delivering' AND d.lease_until IS NOT NULL AND d.lease_until<?)
                ORDER BY d.next_attempt_at, d.id
                LIMIT ?{self.dialect.row_lock_clause()}
                """,
                (now_iso, now_iso, limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE deliveries SET status='delivering', lease_until=?, updated_at=? WHERE id=?",
                    (lease_until, utc_now(), row["id"]),
                )
                claimed_row = connection.execute("SELECT * FROM deliveries WHERE id=?", (row["id"],)).fetchone()
                view = self._delivery_view(claimed_row)
                view["sinkType"] = row["sink_type"]
                view["sinkUrl"] = row["sink_url"]
                view["secretEncrypted"] = row["sink_secret_encrypted"]
                claimed.append(view)
        return claimed

    def record_delivery_attempt(
        self,
        delivery_id: str,
        *,
        status_code: int | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        next_attempt_at: str | None = None,
    ) -> dict[str, Any]:
        """Append an attempt to the append-only history and refresh delivery stats.

        When ``error`` is provided the delivery moves to ``failed`` so the
        claimer can retry it after ``next_attempt_at``; otherwise the status is
        untouched and the caller finishes with ``mark_delivery_delivered`` or
        ``mark_delivery_dead_lettered``.
        """

        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute("SELECT status, attempt_count FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if row is None:
                raise KeyError(delivery_id)
            attempt_no = int(row["attempt_count"]) + 1
            connection.execute(
                """
                INSERT INTO delivery_attempts(id, delivery_id, attempt_no, started_at, finished_at, status_code, error)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_id("delivery_attempt", f"{delivery_id}_{attempt_no}", 64),
                    delivery_id,
                    attempt_no,
                    started_at or now,
                    finished_at or now,
                    status_code,
                    error,
                ),
            )
            connection.execute(
                """
                UPDATE deliveries
                SET attempt_count=?, last_status_code=?, last_error=?,
                    next_attempt_at=COALESCE(?, next_attempt_at),
                    status=?, updated_at=?
                WHERE id=?
                """,
                (attempt_no, status_code, error, next_attempt_at, "failed" if error is not None else str(row["status"]), now, delivery_id),
            )
            return self._delivery_view(
                connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            )

    def mark_delivery_delivered(self, delivery_id: str) -> dict[str, Any]:
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM deliveries WHERE id=?", (delivery_id,)).fetchone() is None:
                raise KeyError(delivery_id)
            connection.execute(
                "UPDATE deliveries SET status='delivered', lease_until=NULL, next_attempt_at=NULL, updated_at=? WHERE id=?",
                (utc_now(), delivery_id),
            )
            return self._delivery_view(connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())

    def mark_delivery_dead_lettered(self, delivery_id: str, *, error: str | None = None) -> dict[str, Any]:
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM deliveries WHERE id=?", (delivery_id,)).fetchone() is None:
                raise KeyError(delivery_id)
            connection.execute(
                "UPDATE deliveries SET status='dead_lettered', lease_until=NULL, "
                "last_error=COALESCE(?, last_error), updated_at=? WHERE id=?",
                (error, utc_now(), delivery_id),
            )
            return self._delivery_view(connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())

    def list_deliveries_for_collector(self, collector_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM deliveries WHERE collector_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
                (collector_id, limit),
            ).fetchall()
        return [self._delivery_view(row) for row in rows]

    def redeliver_delivery(self, delivery_id: str) -> dict[str, Any]:
        """Manually reset a delivery to ``pending`` keeping its id and attempt history."""

        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute("SELECT status FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if row is None:
                raise KeyError(delivery_id)
            if row["status"] == "delivering":
                raise ValueError("delivery is actively being delivered; wait for its lease to expire")
            connection.execute(
                """
                UPDATE deliveries
                SET status='pending', next_attempt_at=?, lease_until=NULL, redelivery_count=redelivery_count+1, updated_at=?
                WHERE id=?
                """,
                (now, now, delivery_id),
            )
            return self._delivery_view(connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone())

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        return self._delivery_view(row) if row else None

    def list_delivery_attempts(self, delivery_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM delivery_attempts WHERE delivery_id=? ORDER BY attempt_no",
                (delivery_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "deliveryId": row["delivery_id"],
                "attemptNo": int(row["attempt_no"]),
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
                "statusCode": row["status_code"],
                "error": row["error"],
            }
            for row in rows
        ]

    @staticmethod
    def _delivery_view(row: Any, include_sink: bool = False) -> dict[str, Any]:
        view = {
            "id": row["id"],
            "collectorId": row["collector_id"],
            "sinkId": row["sink_id"],
            "sinkVersionId": row["sink_version_id"],
            "itemEventId": row["item_event_id"],
            "status": row["status"],
            "attemptCount": int(row["attempt_count"]),
            "nextAttemptAt": row["next_attempt_at"],
            "leaseUntil": row["lease_until"],
            "lastStatusCode": row["last_status_code"],
            "lastError": row["last_error"],
            "redeliveryCount": int(row["redelivery_count"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if include_sink:
            view.update(sinkType=row["sink_type"], sinkUrl=row["sink_url"], secretEncrypted=row["sink_secret_encrypted"])
        return view

    def count_collectors_by_status(self) -> dict[str, int]:
        """Count collectors grouped by their lifecycle status (JSON payload field)."""

        status_expression = self.dialect.json_extract_text("data", "status")
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT {status_expression} AS status, COUNT(*) AS total FROM collectors GROUP BY {status_expression}"
            ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def count_runs_by_status(self, *, within_days: int | None = None) -> dict[str, int]:
        """Count runs grouped by their run status (JSON payload field).

        ``within_days`` restricts the count to runs created at or after
        ``now - within_days``. Timestamps are ISO-8601 TEXT on both dialects,
        so the comparison is the lexicographic string comparison both engines
        apply to text columns.
        """

        if within_days is not None and within_days < 0:
            raise ValueError("within_days must be non-negative")
        status_expression = self.dialect.json_extract_text("data", "status")
        where = ""
        params: tuple[Any, ...] = ()
        if within_days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=within_days)).isoformat().replace("+00:00", "Z")
            where = "WHERE created_at>=?"
            params = (cutoff,)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT {status_expression} AS status, COUNT(*) AS total FROM runs {where} GROUP BY {status_expression}",
                params,
            ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def count_items_by_decision(self) -> dict[str, int]:
        """Count items grouped by their review decision (JSON payload field)."""

        decision_expression = self.dialect.json_extract_text("data", "decision")
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT {decision_expression} AS decision, COUNT(*) AS total FROM items GROUP BY {decision_expression}"
            ).fetchall()
        return {str(row["decision"]): int(row["total"]) for row in rows}

    def count_deliveries_by_status(self) -> dict[str, int]:
        """Count webhook deliveries grouped by their delivery status column."""

        with self.connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS total FROM deliveries GROUP BY status").fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def count_sinks_by_enabled(self) -> dict[str, int]:
        """Count sinks split by their boolean enabled column, zero-filled."""

        with self.connect() as connection:
            rows = connection.execute("SELECT enabled, COUNT(*) AS total FROM sinks GROUP BY enabled").fetchall()
        counts = {"enabled": 0, "disabled": 0}
        for row in rows:
            counts["enabled" if bool(row["enabled"]) else "disabled"] = int(row["total"])
        return counts

    def recent_run_statuses(self, collector_id: str, limit: int) -> list[str]:
        """Return the ``limit`` most recent run statuses for a collector, newest first."""

        if limit < 1:
            raise ValueError("limit must be positive")
        status_expression = self.dialect.json_extract_text("data", "status")
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT {status_expression} AS status FROM runs WHERE collector_id=? "
                "ORDER BY created_at DESC, updated_at DESC, id DESC LIMIT ?",
                (collector_id, limit),
            ).fetchall()
        return [str(row["status"]) for row in rows]

    def list_runs_for_collector(
        self,
        collector_id: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """List run views for one collector in deterministic creation order.

        ``since``/``until`` are inclusive ISO-8601 bounds compared
        lexicographically against the runs table ``created_at`` TEXT column
        (both dialects store timestamps as ISO-8601 UTC strings).
        """

        clauses = ["collector_id=?"]
        params: list[Any] = [collector_id]
        if since:
            clauses.append("created_at>=?")
            params.append(since)
        if until:
            clauses.append("created_at<=?")
            params.append(until)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT data, created_at FROM runs WHERE {' AND '.join(clauses)} ORDER BY created_at, id",
                tuple(params),
            ).fetchall()
        return [run for row in rows if (run := self._decode_run(row)) is not None]

    def list_rule_versions_for_collector(self, collector_id: str) -> list[dict[str, Any]]:
        """List immutable rule versions for a collector, each with its latest attestation.

        Wraps the per-rule-version read paths (``get_rule_version`` storage and
        ``latest_rule_attestation``) inside a single connection so the returned
        views pair every ``gatherSpec`` with the Ed25519 attestation record that
        authorized its publication.
        """

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT data FROM rule_versions WHERE collector_id=? ORDER BY created_at, id",
                (collector_id,),
            ).fetchall()
            versions: list[dict[str, Any]] = []
            for row in rows:
                version = self.dialect.decode_json(row["data"])
                versions.append({**version, "attestation": self.latest_rule_attestation(str(version["id"]), connection)})
        return versions

    def list_items_for_collector_window(
        self,
        collector_id: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield a collector's items whose ``observedAt`` falls inside the window.

        Follows the ``list_items_cursor`` JSON-extract ordering contract:
        ``(observedAt DESC, entityKey DESC, id DESC)``. ``since``/``until`` are
        inclusive bounds compared lexicographically against the ISO-8601
        ``observedAt`` payload field, mirroring the ``created_at`` TEXT
        comparisons used by ``count_runs_by_status``.
        """

        observed_at = self.dialect.json_extract_text("data", "observedAt")
        entity_key_expression = self.dialect.json_extract_text("data", "entityKey")
        clauses, params = self._item_filter_clauses(
            collector_id=collector_id,
            run_id=None,
            decision=None,
            entity_key=None,
        )
        if since:
            clauses.append(f"{observed_at}>=?")
            params.append(since)
        if until:
            clauses.append(f"{observed_at}<=?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}"
        connection = self.connect()
        try:
            cursor = connection.execute(
                f"SELECT data FROM items {where} ORDER BY {observed_at} DESC, {entity_key_expression} DESC, id DESC",
                tuple(params),
            )
            while batch := cursor.fetchmany(500):
                for row in batch:
                    yield self.dialect.decode_json(row["data"])
        finally:
            connection.close()

    def get_platform_setting_value(self, key: str) -> str | None:
        """Return the scalar value of a platform setting, or ``None`` when unset.

        Complements the JSON-blob ``get_platform_setting`` (model configuration):
        Settings-UI toggles (v0.6) are plain strings in
        ``platform_setting_values`` with an audit trail.
        """

        with self.connect() as connection:
            row = connection.execute("SELECT value FROM platform_setting_values WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def get_platform_setting_value_detail(self, key: str) -> dict[str, Any] | None:
        """Return ``{key, value, updatedBy, updatedAt}`` for a platform setting row."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT key, value, updated_by, updated_at FROM platform_setting_values WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        return {
            "key": str(row["key"]),
            "value": str(row["value"]),
            "updatedBy": row["updated_by"],
            "updatedAt": row["updated_at"],
        }

    def set_platform_setting_value(self, key: str, value: str, *, updated_by: str | None) -> dict[str, Any]:
        """Upsert a scalar platform setting, recording who changed it and when."""

        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO platform_setting_values(key, value, updated_by, updated_at) VALUES(?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at
                """,
                (key, value, updated_by, now),
            )
        return {"key": key, "value": value, "updatedBy": updated_by, "updatedAt": now}

    def effective_allow_http_public(self) -> bool:
        """Resolve the effective anonymous-HTTP collection policy (v0.6).

        The ``allowAnonymousHttp`` platform row — seeded ``'true'`` by migration
        002 and managed from the Settings UI — wins when present; while it is
        absent the config default ``settings.allow_http_public`` applies. Any
        stored value other than ``'true'`` (case-insensitive) counts as
        disallowing anonymous HTTP. The credential-HTTPS hard line is unrelated
        and always enforced by ``normalize_source_url``.
        """

        raw = self.get_platform_setting_value("allowAnonymousHttp")
        if raw is not None:
            return raw.strip().lower() == "true"
        return get_settings().allow_http_public
