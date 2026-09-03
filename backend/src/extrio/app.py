import asyncio
import copy
import csv
import io
import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import uvicorn
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from extrio.auth import (
    allow_login,
    hash_password,
    new_session,
    session_token_hash,
    validate_display_name,
    validate_password,
    validate_username,
    verify_password,
)
from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.demo import router as demo_router
from extrio.harvest import discover_records_from_spec, make_item
from extrio.integrity import (
    IntegrityError,
    LocalEd25519Signer,
    build_rule_attestation,
    calculate_rule_digest,
    digest_value,
    immutable_rule_version,
    verify_rule_attestation,
)
from extrio.security import SourceUrlError, normalize_source_url
from extrio.store import (
    DEFAULT_COLLECTION_ID,
    DEFAULT_COLLECTION_NAME,
    EXPORT_ITEMS_CAP,
    AuthSetupComplete,
    IdempotencyConflict,
    InvalidCursor,
    Store,
    stable_id,
)

settings = get_settings()
store = Store(settings.database_path)
contracts = ContractBundle(settings.contracts_path)
rule_signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
credential_cipher = CredentialCipher(settings.credential_encryption_key_path)
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
ALLOWED_REVIEW_DECISIONS = {"approved", "risk_accepted", "excluded"}
ALLOWED_MODEL_PROVIDERS = {"openai", "deepseek", "qwen", "custom"}
MODEL_PROVIDER_NAMES = {"openai": "OpenAI", "deepseek": "DeepSeek", "qwen": "阿里云百炼", "custom": "OpenAI 兼容服务"}
mutation_lock = threading.RLock()
logger = logging.getLogger(__name__)
RUNTIME_METRIC_DEFAULTS = {
    "listPagesFetched": 0,
    "detailUrlsDiscovered": 0,
    "detailPagesFetched": 0,
    "recordsOutsideWindow": 0,
    "duplicateDetailUrls": 0,
    "newItems": 0,
    "updatedItems": 0,
    "unchangedItems": 0,
    "warningCount": 0,
}


def backfill_v02_response_contract() -> None:
    for collector in store.list_collectors():
        changed = False
        if "collectionId" not in collector:
            collector["collectionId"] = DEFAULT_COLLECTION_ID
            changed = True
        if "collectionName" not in collector:
            collector["collectionName"] = DEFAULT_COLLECTION_NAME
            changed = True
        if changed:
            store.save_collector(collector)

    for operation in store.list_operations():
        metrics = {**RUNTIME_METRIC_DEFAULTS, **operation.get("metrics", {})}
        if metrics != operation.get("metrics"):
            store.update_operation(operation["id"], metrics=metrics)

    for run in store.list_runs():
        changed = False
        defaults = {
            "recordsOutsideWindow": 0,
            "duplicateDetailUrls": 0,
            "newItems": 0,
            "updatedItems": 0,
            "unchangedItems": 0,
            "policyContextStatus": "fixed" if run.get("policyVersion") else "legacy_unavailable",
            "policyVersion": None,
            "policyDigest": None,
            "executionMode": None,
            "windowStart": None,
            "checkpointBefore": None,
            "checkpointAfter": None,
        }
        for key, value in defaults.items():
            if key not in run:
                run[key] = value
                changed = True
        for item in run.get("items", []):
            if "changeType" not in item:
                item["changeType"] = None
                changed = True
        if changed:
            store.save_run(run)

    items_by_run: dict[str, list[dict[str, Any]]] = {}
    changed_item_runs: set[str] = set()
    for item in store.list_items():
        run_id = item["lineage"]["runId"]
        if "changeType" not in item:
            item["changeType"] = None
            changed_item_runs.add(run_id)
        items_by_run.setdefault(run_id, []).append(item)
    for run_id, items in items_by_run.items():
        if run_id in changed_item_runs:
            store.save_items(run_id, items)


async def schedule_dispatch_loop() -> None:
    while True:
        try:
            with mutation_lock:
                occurrences = store.claim_due_schedules()
            for occurrence in occurrences:
                try:
                    with mutation_lock:
                        operation = create_run_operation(occurrence["collectorId"])
                    store.finish_schedule_occurrence(
                        occurrence["occurrenceKey"],
                        status="dispatched",
                        run_id=operation["resourceId"],
                        reason=None,
                    )
                except RunStartError as exc:
                    store.finish_schedule_occurrence(
                        occurrence["occurrenceKey"],
                        status="skipped",
                        run_id=None,
                        reason=exc.code,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Schedule dispatch failed")
        await asyncio.sleep(settings.schedule_poll_seconds)


def persist_published_rule(
    collector: dict[str, Any],
    *,
    rule_version_id: str,
    review_decisions: dict[str, str],
    request_id: str,
    actor_id: str,
    action: str = "rule.published",
) -> dict[str, Any]:
    rule_version = immutable_rule_version(
        collector_id=collector["id"],
        spec=collector["candidate"]["gatherSpec"],
        rule_version_id=rule_version_id,
        tenant_id=settings.tenant_id,
    )
    signing_key = store.ensure_signing_key(rule_signer.trust_record(tenant_id=settings.tenant_id, revision=1))
    if signing_key["status"] != "trusted":
        raise IntegrityError("configured signing key is not trusted for publishing")
    attestation = build_rule_attestation(
        spec=rule_version["gatherSpec"],
        rule_version_id=rule_version_id,
        review_decisions=review_decisions,
        signer=rule_signer,
        contracts=contracts,
        tenant_id=settings.tenant_id,
    )
    rule_version["ruleDigest"] = attestation["ruleDigest"]
    candidate = copy.deepcopy(collector["candidate"])
    candidate["gatherSpec"] = rule_version["gatherSpec"]
    candidate["digest"] = digest_value(rule_version["gatherSpec"])
    return store.publish_rule_bundle(
        collector_id=collector["id"],
        rule_version=rule_version,
        attestation=attestation,
        collector_changes={
            "status": "published",
            "activeRuleVersion": rule_version_id,
            "reviewDecisions": review_decisions,
            "candidate": candidate,
            "updatedAt": "刚刚",
        },
        audit={
            "actorId": actor_id,
            "action": action,
            "requestId": request_id,
            "details": {"attestationId": attestation["attestationId"], "keyId": attestation["keyId"]},
        },
    )


def verified_run_integrity(collector: dict[str, Any]) -> dict[str, Any]:
    rule_version_id = collector.get("activeRuleVersion")
    rule_version = store.get_rule_version(rule_version_id) if rule_version_id else None
    attestation = store.latest_rule_attestation(rule_version_id) if rule_version_id else None
    signing_key = store.get_signing_key(attestation["keyId"]) if attestation else None
    if not rule_version or not attestation or not signing_key:
        raise IntegrityError("published rule does not have a complete integrity bundle")
    verified = verify_rule_attestation(
        spec=rule_version["gatherSpec"],
        attestation=attestation,
        signing_key=signing_key,
        contracts=contracts,
        expected_rule_version_id=rule_version_id,
        expected_tenant_id=settings.tenant_id,
    )
    return {**verified, "ruleVersionId": rule_version_id}


def next_rule_version_id(collector_id: str, version: int) -> str:
    token = collector_id.removeprefix("collector_")
    suffix = f"_v{version}"
    return f"rule_{token[: 128 - len('rule_') - len(suffix)]}{suffix}"


def platform_error(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    *,
    pointer: str | None = None,
    retryable: bool = False,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:16]}")
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "requestId": request_id, "retryable": retryable, "pointer": pointer, "details": {}},
        headers={"X-Request-ID": request_id},
    )


def page(items: list[dict[str, Any]], limit: int = 50) -> dict[str, Any]:
    return {"items": items[:limit], "page": {"nextCursor": None}}


def model_setting_view(value: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = value or {
        "provider": settings.model_provider,
        "baseUrl": settings.model_base_url,
        "model": settings.model_name,
        "secretRef": settings.model_secret_ref,
        "updatedAt": None,
    }
    secret_ref = str(configured.get("secretRef", ""))
    secret_name = secret_ref.removeprefix("env:") if secret_ref.startswith("env:") else ""
    return {
        "provider": configured.get("provider", "openai"),
        "baseUrl": configured.get("baseUrl", ""),
        "model": configured.get("model", ""),
        "secretRef": secret_ref,
        "secretConfigured": bool(secret_name and os.getenv(secret_name)),
        "updatedAt": configured.get("updatedAt"),
    }


def provider_credentials() -> dict[str, str]:
    stored = store.get_platform_setting("model-provider-credentials") or {}
    credentials = stored.get("credentials", {})
    return credentials if isinstance(credentials, dict) else {}


def model_configuration_view(value: dict[str, Any] | None = None) -> dict[str, Any]:
    configured = value
    if configured is None:
        legacy = store.get_platform_setting("model")
        provider = legacy or {
            "provider": settings.model_provider,
            "baseUrl": settings.model_base_url,
            "model": settings.model_name,
            "secretRef": settings.model_secret_ref,
            "updatedAt": None,
        }
        provider_id = "provider_default"
        model_id = "model_default"
        configured = {
            "providers": [{
                "id": provider_id,
                "name": MODEL_PROVIDER_NAMES.get(str(provider.get("provider", "openai")), "模型供应商"),
                "provider": provider.get("provider", "openai"),
                "baseUrl": provider.get("baseUrl", ""),
                "secretRef": provider.get("secretRef", ""),
                "enabled": True,
                "updatedAt": provider.get("updatedAt"),
            }],
            "models": ([{
                "id": model_id,
                "providerId": provider_id,
                "modelId": provider.get("model", ""),
                "enabled": True,
                "updatedAt": provider.get("updatedAt"),
            }] if provider.get("model") else []),
            "defaultModelId": model_id if provider.get("model") else None,
            "updatedAt": provider.get("updatedAt"),
        }

    encrypted_credentials = provider_credentials()
    default_model_id = configured.get("defaultModelId")
    providers = []
    for provider in configured.get("providers", []):
        secret_ref = str(provider.get("secretRef", ""))
        secret_name = secret_ref.removeprefix("env:") if secret_ref.startswith("env:") else ""
        providers.append({
            "id": provider.get("id", ""),
            "name": provider.get("name", ""),
            "provider": provider.get("provider", "openai"),
            "baseUrl": provider.get("baseUrl", ""),
            "enabled": provider.get("enabled", True),
            "credentialConfigured": credential_cipher.can_decrypt(encrypted_credentials.get(str(provider.get("id", ""))))
            or bool(secret_name and os.getenv(secret_name)),
            "updatedAt": provider.get("updatedAt", configured.get("updatedAt")),
        })
    models = [
        {
            **model,
            "isDefault": model.get("id") == default_model_id,
            "updatedAt": model.get("updatedAt", configured.get("updatedAt")),
        }
        for model in configured.get("models", [])
    ]
    return {
        "providers": providers,
        "models": models,
        "defaultModelId": default_model_id,
        "updatedAt": configured.get("updatedAt"),
    }


def validate_model_configuration(body: dict[str, Any], request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    providers = body.get("providers")
    models = body.get("models")
    default_model_id = body.get("defaultModelId")
    if not isinstance(providers, list) or not isinstance(models, list):
        return None, platform_error(request, "VALIDATION_FAILED", "供应商与模型必须是数组", 422, pointer="/providers")

    provider_ids: set[str] = set()
    provider_names: set[str] = set()
    normalized_providers = []
    for index, provider in enumerate(providers):
        pointer = f"/providers/{index}"
        required_fields = {"id", "name", "provider", "baseUrl", "enabled"}
        allowed_fields = required_fields | {"apiKey"}
        if not isinstance(provider, dict) or not required_fields.issubset(provider) or not set(provider).issubset(allowed_fields):
            return None, platform_error(request, "VALIDATION_FAILED", "供应商字段与 API 合同不一致", 422, pointer=pointer)
        provider_id = str(provider.get("id", "")).strip()
        name = str(provider.get("name", "")).strip()
        provider_type = str(provider.get("provider", "")).strip()
        base_url = str(provider.get("baseUrl", "")).strip().rstrip("/")
        api_key_value = provider.get("apiKey")
        if api_key_value is not None and not isinstance(api_key_value, str):
            return None, platform_error(request, "VALIDATION_FAILED", "API Key 必须是字符串", 422, pointer=f"{pointer}/apiKey")
        api_key = api_key_value.strip() if isinstance(api_key_value, str) else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", provider_id) or provider_id in provider_ids:
            return None, platform_error(request, "VALIDATION_FAILED", "供应商 ID 无效或重复", 422, pointer=f"{pointer}/id")
        if not name or name.casefold() in provider_names:
            return None, platform_error(request, "VALIDATION_FAILED", "供应商名称不能为空或重复", 422, pointer=f"{pointer}/name")
        if provider_type not in ALLOWED_MODEL_PROVIDERS:
            return None, platform_error(request, "VALIDATION_FAILED", "不支持的模型供应商", 422, pointer=f"{pointer}/provider")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            return None, platform_error(
                request, "VALIDATION_FAILED", "模型 API 地址必须是有效的 HTTPS URL", 422, pointer=f"{pointer}/baseUrl"
            )
        if not isinstance(provider.get("enabled"), bool):
            return None, platform_error(request, "VALIDATION_FAILED", "供应商启用状态必须是布尔值", 422, pointer=f"{pointer}/enabled")
        provider_ids.add(provider_id)
        provider_names.add(name.casefold())
        normalized_providers.append({
            "id": provider_id,
            "name": name,
            "provider": provider_type,
            "baseUrl": base_url,
            "enabled": provider["enabled"],
            "apiKey": api_key or None,
        })

    model_ids: set[str] = set()
    provider_model_ids: set[tuple[str, str]] = set()
    normalized_models = []
    for index, model in enumerate(models):
        pointer = f"/models/{index}"
        if not isinstance(model, dict) or set(model) != {"id", "providerId", "modelId", "enabled"}:
            return None, platform_error(request, "VALIDATION_FAILED", "模型字段与 API 合同不一致", 422, pointer=pointer)
        model_id = str(model.get("id", "")).strip()
        provider_id = str(model.get("providerId", "")).strip()
        provider_model_id = str(model.get("modelId", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", model_id) or model_id in model_ids:
            return None, platform_error(request, "VALIDATION_FAILED", "模型配置 ID 无效或重复", 422, pointer=f"{pointer}/id")
        if provider_id not in provider_ids:
            return None, platform_error(request, "VALIDATION_FAILED", "模型引用的供应商不存在", 422, pointer=f"{pointer}/providerId")
        if not provider_model_id or (provider_id, provider_model_id.casefold()) in provider_model_ids:
            return None, platform_error(
                request, "VALIDATION_FAILED", "同一供应商下的模型 ID 不能为空或重复", 422, pointer=f"{pointer}/modelId"
            )
        if not isinstance(model.get("enabled"), bool):
            return None, platform_error(request, "VALIDATION_FAILED", "模型启用状态必须是布尔值", 422, pointer=f"{pointer}/enabled")
        model_ids.add(model_id)
        provider_model_ids.add((provider_id, provider_model_id.casefold()))
        normalized_models.append({
            "id": model_id,
            "providerId": provider_id,
            "modelId": provider_model_id,
            "enabled": model["enabled"],
        })

    if default_model_id is not None:
        default = next((model for model in normalized_models if model["id"] == default_model_id), None)
        provider = next((row for row in normalized_providers if default and row["id"] == default["providerId"]), None)
        if not default or not default["enabled"] or not provider or not provider["enabled"]:
            return None, platform_error(
                request, "VALIDATION_FAILED", "默认模型必须来自已启用的供应商和模型", 422, pointer="/defaultModelId"
            )

    return {
        "providers": normalized_providers,
        "models": normalized_models,
        "defaultModelId": default_model_id,
    }, None


def legacy_model_setting_from_configuration(configured: dict[str, Any]) -> dict[str, Any]:
    view = model_configuration_view(configured)
    model = next((row for row in view["models"] if row["id"] == view["defaultModelId"]), None)
    provider = next((row for row in view["providers"] if model and row["id"] == model["providerId"]), None)
    provider = provider or next(iter(view["providers"]), None)
    return {
        "provider": provider["provider"] if provider else "openai",
        "baseUrl": provider["baseUrl"] if provider else "",
        "model": model["modelId"] if model else "",
        "secretRef": "",
        "secretConfigured": provider["credentialConfigured"] if provider else False,
        "updatedAt": view["updatedAt"],
    }


def require_idempotency(request: Request, key: str | None) -> JSONResponse | None:
    if not key or not 16 <= len(key) <= 128:
        return platform_error(request, "IDEMPOTENCY_KEY_REQUIRED", "缺少有效的 Idempotency-Key", 400, pointer="/headers/Idempotency-Key")
    return None


def replay(scope: str, key: str, body: Any, request: Request) -> JSONResponse | None:
    try:
        result = store.idempotency_replay(scope, key, body)
    except IdempotencyConflict:
        return platform_error(request, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key 已被不同请求占用", 409)
    if result is None:
        return None
    status, value = result
    return JSONResponse(value, status_code=status, headers={"X-Request-ID": request.state.request_id, "Idempotency-Replayed": "true"})


def remember(scope: str, key: str, body: Any, status: int, value: dict[str, Any]) -> None:
    store.remember_idempotency(scope, key, body, status, value)


async def read_contract_body(
    request: Request,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return None, platform_error(request, "VALIDATION_FAILED", "请求体必须是有效 JSON 对象", 422, pointer="/")
    fields = set(body) if isinstance(body, dict) else set()
    allowed = required | (optional or set())
    if not isinstance(body, dict) or not required.issubset(fields) or not fields.issubset(allowed):
        return None, platform_error(request, "VALIDATION_FAILED", "请求字段与 API 合同不一致", 422, pointer="/")
    return body, None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.initialize()
    if settings.seed_demo and not store.list_collectors():
        store.create_collector(
            "北京市公共资源交易演示源",
            "采集公开招标公告，提取项目名称、采购单位、发布日期、预算和详情链接。",
            f"http://{settings.host}:{settings.port}/demo/tenders",
            settings.host,
        )
    for collector in store.list_collectors():
        collector = store.ensure_collection_policy(collector["id"])
        collector = store.ensure_schedule(collector["id"])
        if settings.seed_demo:
            if (
                collector.get("status") == "published"
                and collector.get("activeRuleVersion")
                and collector.get("candidate")
                and store.get_rule_version(collector["activeRuleVersion"]) is None
            ):
                persist_published_rule(
                    collector,
                    rule_version_id=collector["activeRuleVersion"],
                    review_decisions=collector.get("reviewDecisions") or {},
                    request_id="startup_integrity_migration",
                    actor_id="system_startup",
                    action="rule.integrity_bootstrapped",
                )
    backfill_v02_response_contract()
    schedule_task = asyncio.create_task(schedule_dispatch_loop())
    try:
        yield
    finally:
        schedule_task.cancel()
        with suppress(asyncio.CancelledError):
            await schedule_task


app = FastAPI(title="Extrio Control Plane API", version="1.14.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["Location", "Retry-After", "X-Request-ID", "Idempotency-Replayed"],
)
app.include_router(demo_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    request.state.request_id = incoming if re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", incoming) else f"req_{uuid.uuid4().hex[:20]}"

    request.state.auth_user = None
    if not settings.auth_enabled:
        request.state.auth_user = {
            "id": "user_local_development",
            "username": "local",
            "displayName": "Local Administrator",
            "role": "administrator",
        }
    else:
        token = request.cookies.get(settings.auth_cookie_name, "")
        if token:
            request.state.auth_user = store.get_auth_session(session_token_hash(token))

        public_path = (
            request.url.path == "/healthz"
            or request.url.path.startswith("/demo/")
            or request.url.path in {
                "/api/v1/auth/state",
                "/api/v1/auth/setup",
                "/api/v1/auth/login",
            }
        )
        if request.method != "OPTIONS" and not public_path and request.state.auth_user is None:
            return platform_error(request, "AUTH_REQUIRED", "请先登录", 401)

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin and origin not in settings.cors_origin_list:
                return platform_error(request, "FORBIDDEN", "请求来源不受信任", 403)

    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    location = exc.errors()[0].get("loc", ()) if exc.errors() else ()
    pointer = "/" + "/".join(str(part) for part in location)
    return platform_error(request, "VALIDATION_FAILED", "请求不符合 API 合同", 422, pointer=pointer)


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    return platform_error(request, "INTERNAL_ERROR", "服务内部错误", 500, retryable=True)


@app.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok", "contract": "extrio.control-plane.v1"}


def auth_state_view(request: Request) -> dict[str, Any]:
    return {
        "authEnabled": settings.auth_enabled,
        "setupRequired": settings.auth_enabled and store.auth_setup_required(),
        "authenticated": request.state.auth_user is not None,
        "user": request.state.auth_user,
    }


def authenticated_response(request: Request, user: dict[str, Any]) -> JSONResponse:
    token, token_hash, expires_at = new_session(settings.auth_session_hours)
    store.create_auth_session(token_hash=token_hash, user_id=user["id"], expires_at=expires_at)
    response = JSONResponse({**auth_state_view(request), "setupRequired": False, "authenticated": True, "user": user})
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        max_age=settings.auth_session_hours * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/api/v1/auth/state")
def get_auth_state(request: Request):
    return auth_state_view(request)


@app.post("/api/v1/auth/setup")
async def setup_auth(request: Request):
    if not settings.auth_enabled:
        return platform_error(request, "FORBIDDEN", "当前部署未启用身份认证", 409)
    body, body_error = await read_contract_body(request, required={"username", "password"}, optional={"displayName"})
    if body_error:
        return body_error
    try:
        username = validate_username(body["username"])
        password = validate_password(body["password"])
        display_name = validate_display_name(body.get("displayName"), username)
        user = store.create_first_auth_user(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
        )
    except ValueError as exc:
        return platform_error(request, "VALIDATION_FAILED", str(exc), 422)
    except AuthSetupComplete:
        return platform_error(request, "SETUP_ALREADY_COMPLETED", "管理员初始化已经完成", 409)
    request.state.auth_user = user
    return authenticated_response(request, user)


@app.post("/api/v1/auth/login")
async def login(request: Request):
    if not settings.auth_enabled:
        return platform_error(request, "FORBIDDEN", "当前部署未启用身份认证", 409)
    body, body_error = await read_contract_body(request, required={"username", "password"})
    if body_error:
        return body_error
    username = str(body.get("username", "")).strip()
    client_host = request.client.host if request.client else "unknown"
    if not allow_login(f"{client_host}:{username.casefold()}", settings.auth_login_limit):
        response = platform_error(request, "RATE_LIMITED", "登录尝试过于频繁，请稍后再试", 429, retryable=True)
        response.headers["Retry-After"] = "60"
        return response
    credentials = store.get_auth_credentials(username)
    valid = verify_password(str(body.get("password", "")), credentials.get("passwordHash") if credentials else None)
    if not valid or credentials is None:
        return platform_error(request, "INVALID_CREDENTIALS", "用户名或密码不正确", 401)
    user = {key: value for key, value in credentials.items() if key != "passwordHash"}
    request.state.auth_user = user
    return authenticated_response(request, user)


@app.post("/api/v1/auth/logout")
def logout(request: Request):
    token = request.cookies.get(settings.auth_cookie_name, "")
    if token:
        store.delete_auth_session(session_token_hash(token))
    request.state.auth_user = None
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(settings.auth_cookie_name, path="/", samesite="strict", secure=settings.auth_cookie_secure)
    return response


@app.get("/gather-spec.schema.json", include_in_schema=False)
def gather_spec_schema() -> JSONResponse:
    return JSONResponse(contracts.gather_schema)


@app.get("/api/v1/collectors")
def list_collectors(limit: int = 50):
    return page(store.list_collectors(), limit)


@app.get("/api/v1/settings/model")
def get_model_setting():
    configured = store.get_platform_setting("model-configurations")
    return legacy_model_setting_from_configuration(configured) if configured else model_setting_view(store.get_platform_setting("model"))


@app.put("/api/v1/settings/model")
async def update_model_setting(request: Request, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required={"provider", "baseUrl", "model", "secretRef"})
    if body_error:
        return body_error
    scope = "PUT:/settings/model"
    if found := replay(scope, idempotency_key, body, request):
        return found
    provider = str(body.get("provider", "")).strip()
    base_url = str(body.get("baseUrl", "")).strip().rstrip("/")
    model = str(body.get("model", "")).strip()
    secret_ref = str(body.get("secretRef", "")).strip()
    if provider not in ALLOWED_MODEL_PROVIDERS:
        return platform_error(request, "VALIDATION_FAILED", "不支持的模型供应商", 422, pointer="/provider")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return platform_error(request, "VALIDATION_FAILED", "模型 API 地址必须是有效的 HTTPS URL", 422, pointer="/baseUrl")
    if not model:
        return platform_error(request, "VALIDATION_FAILED", "模型 ID 不能为空", 422, pointer="/model")
    if not re.fullmatch(r"env:[A-Z][A-Z0-9_]{2,127}", secret_ref):
        return platform_error(request, "VALIDATION_FAILED", "密钥引用必须使用 env:VARIABLE_NAME 格式", 422, pointer="/secretRef")
    saved = store.save_platform_setting(
        "model",
        {"provider": provider, "baseUrl": base_url, "model": model, "secretRef": secret_ref},
    )
    store.save_platform_setting("model-configurations", {
        "providers": [{
            "id": "provider_legacy",
            "name": MODEL_PROVIDER_NAMES.get(provider, "模型供应商"),
            "provider": provider,
            "baseUrl": base_url,
            "secretRef": secret_ref,
            "enabled": True,
        }],
        "models": [{"id": "model_legacy", "providerId": "provider_legacy", "modelId": model, "enabled": True}],
        "defaultModelId": "model_legacy",
    })
    value = model_setting_view(saved)
    remember(scope, idempotency_key, body, 200, value)
    return value


@app.get("/api/v1/settings/models")
def get_model_configuration():
    return model_configuration_view(store.get_platform_setting("model-configurations"))


@app.put("/api/v1/settings/models")
async def update_model_configuration(request: Request, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required={"providers", "models", "defaultModelId"})
    if body_error:
        return body_error
    scope = "PUT:/settings/models"
    if found := replay(scope, idempotency_key, body, request):
        return found
    normalized, validation_error = validate_model_configuration(body, request)
    if validation_error:
        return validation_error
    existing_credentials = provider_credentials()
    existing_configuration = store.get_platform_setting("model-configurations") or {}
    legacy_secret_refs = {
        str(provider.get("id")): str(provider.get("secretRef"))
        for provider in existing_configuration.get("providers", [])
        if provider.get("secretRef")
    }
    if not existing_configuration and settings.model_secret_ref:
        legacy_secret_refs["provider_default"] = settings.model_secret_ref
    next_credentials: dict[str, str] = {}
    normalized_providers = []
    for provider in normalized["providers"]:
        api_key = provider.pop("apiKey", None)
        provider_id = provider["id"]
        if api_key:
            next_credentials[provider_id] = credential_cipher.encrypt(api_key)
        elif provider_id in existing_credentials:
            next_credentials[provider_id] = existing_credentials[provider_id]
        elif provider_id in legacy_secret_refs:
            provider["secretRef"] = legacy_secret_refs[provider_id]
        normalized_providers.append(provider)
    normalized["providers"] = normalized_providers
    store.save_platform_setting("model-provider-credentials", {"credentials": next_credentials})
    saved = store.save_platform_setting("model-configurations", normalized)
    value = model_configuration_view(saved)
    remember(scope, idempotency_key, body, 200, value)
    return value


@app.get("/api/v1/collectors/{collector_id}")
def get_collector(collector_id: str, request: Request):
    collector = store.get_collector(collector_id)
    return collector if collector else platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)


@app.patch("/api/v1/collectors/{collector_id}")
async def update_collector_definition(
    collector_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required={"name", "intent", "sourceUrl"})
    if body_error:
        return body_error
    with mutation_lock:
        scope = f"PATCH:/collectors/{collector_id}"
        if found := replay(scope, idempotency_key, body, request):
            return found
        collector = store.get_collector(collector_id)
        if not collector:
            return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
        if collector.get("activeOperationId") or store.has_active_run(collector_id):
            return platform_error(request, "OPERATION_ALREADY_ACTIVE", "异步任务运行期间不能修改采集器定义", 409)
        name = str(body.get("name", "")).strip()
        intent = str(body.get("intent", "")).strip()
        if not name or not intent:
            return platform_error(request, "VALIDATION_FAILED", "name 与 intent 不能为空", 422)
        try:
            source_url, source_host = normalize_source_url(
                body.get("sourceUrl", ""),
                allow_http_localhost=settings.allow_http_localhost,
                allow_http_public=settings.allow_http_public,
            )
        except SourceUrlError as exc:
            return platform_error(request, exc.code, str(exc), 422, pointer="/sourceUrl")
        if store.source_exists(source_url, exclude_collector_id=collector_id):
            return platform_error(request, "SOURCE_ALREADY_EXISTS", "该 Source URL 已存在", 409, pointer="/sourceUrl")

        rule_input_changed = intent != collector["intent"] or source_url != collector["sourceUrl"]
        collector.update(name=name, intent=intent, sourceUrl=source_url, sourceHost=source_host, updatedAt="刚刚")
        if rule_input_changed:
            collector.update(status="draft", candidate=None, previewItems=[], reviewDecisions=None)
        store.save_collector(collector)
        remember(scope, idempotency_key, body, 200, collector)
        return collector


def _valid_selector(value: Any) -> bool:
    return isinstance(value, str) and 5 <= len(value) <= 4096 and value.startswith(("css:", "jsonpath:"))


def _normalize_candidate_pagination(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        return None
    if value["type"] == "none" and set(value) == {"type"}:
        return {"type": "none"}
    if value["type"] == "next_link" and set(value) == {"type", "selector", "maxPages", "allowCrossHost"}:
        if not _valid_selector(value["selector"]) or value["allowCrossHost"] is not False:
            return None
        max_pages = value["maxPages"]
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 100_000:
            return None
        return dict(value)
    if value["type"] == "page" and set(value) == {"type", "parameter", "start", "step", "maxPages", "stopWhenNoItems"}:
        integers = (value["start"], value["step"], value["maxPages"])
        if any(isinstance(item, bool) or not isinstance(item, int) for item in integers):
            return None
        if not str(value["parameter"]).strip() or value["start"] < 0 or not 1 <= value["step"] <= 1_000:
            return None
        if not 1 <= value["maxPages"] <= 100_000 or not isinstance(value["stopWhenNoItems"], bool):
            return None
        return dict(value)
    return None


def _validate_candidate_against_latest_samples(
    collector: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    operation = next(
        (
            item
            for item in store.list_operations()
            if item.get("kind") == "explore"
            and item.get("resourceId") == collector["id"]
            and item.get("status") == "succeeded"
            and (settings.artifact_path / item["id"] / "list-001.html").exists()
        ),
        None,
    )
    if operation is None:
        raise ValueError("没有可用于验证手工规则的最近探索样本，请先重新生成规则")
    artifact_dir = settings.artifact_path / operation["id"]
    list_html = (artifact_dir / "list-001.html").read_text(encoding="utf-8")
    entrypoint = candidate["gatherSpec"]["sourceContext"]["entrypoints"][0]
    records_by_url: dict[str, dict[str, str]] = {}
    if candidate["mode"] == "list_detail":
        records, _next_url = discover_records_from_spec(
            list_html,
            entrypoint,
            candidate["gatherSpec"]["collect"]["list"],
        )
        records_by_url = {record["detailUrl"]: record for record in records}
        if not records:
            raise ValueError("列表 selector 或详情链接 selector 未能从最近样本发现任何详情 URL")
        sampled_urls = set(candidate["discovery"].get("detailUrlSamples", []))
        if sampled_urls and sampled_urls.isdisjoint(record["detailUrl"] for record in records):
            raise ValueError("详情链接 selector 的发现结果与最近探索样本不一致")
        detail_files = sorted(artifact_dir.glob("detail-*.html"))
        detail_urls = candidate["discovery"].get("detailUrlSamples", [])
        samples = [
            (detail_urls[index] if index < len(detail_urls) else records[index]["detailUrl"], path.read_text(encoding="utf-8"))
            for index, path in enumerate(detail_files)
            if index < len(records)
        ]
    else:
        samples = [(collector["sourceUrl"], list_html)]
    if not samples:
        raise ValueError("最近探索没有可用于验证输出字段的详情样本")

    preview_run = {"id": f"preview_manual_{operation['id']}", "ruleVersion": "candidate"}
    candidate_collector = {**collector, "candidate": candidate}
    preview_items = [
        make_item(candidate_collector, preview_run, url, html, index, source_record=records_by_url.get(url))
        for index, (url, html) in enumerate(samples, start=1)
    ]
    accepted = next((item for item in preview_items if item["decision"] == "accepted"), None)
    if accepted is None:
        reason = preview_items[0].get("rejectionReason") or "输出字段未通过质量门"
        raise ValueError(f"手工规则未通过最近样本验证：{reason}")

    evidence_html = samples[0][1]
    soup = BeautifulSoup(evidence_html, "html.parser")
    for field in candidate["fields"]:
        field["sample"] = str(accepted.get(field["key"]) or "字段缺失")[:240]
        selector = field["selector"]
        if selector.startswith("css:"):
            node = soup.select_one(selector.removeprefix("css:").split("::", 1)[0])
            field["evidence"] = str(node)[:500] if node else "最近样本未定位到 DOM 节点"
        field["confidence"] = max(float(field.get("confidence", 0)), 0.9)
    return preview_items


@app.patch("/api/v1/collectors/{collector_id}/candidate-rule")
async def update_candidate_rule(
    collector_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    required = {"listSelector", "detailLinkSelector", "pagination", "fields"}
    allowed = required | {"listFields"}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return platform_error(request, "VALIDATION_FAILED", "请求体必须是有效 JSON 对象", 422, pointer="/")
    if not isinstance(body, dict) or not required.issubset(body) or not set(body).issubset(allowed):
        return platform_error(request, "VALIDATION_FAILED", "请求字段与 API 合同不一致", 422, pointer="/")
    with mutation_lock:
        scope = f"PATCH:/collectors/{collector_id}/candidate-rule"
        if found := replay(scope, idempotency_key, body, request):
            return found
        collector = store.get_collector(collector_id)
        if not collector:
            return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
        if collector.get("activeOperationId") or store.has_active_run(collector_id):
            return platform_error(request, "OPERATION_ALREADY_ACTIVE", "异步任务运行期间不能修改候选规则", 409)
        candidate = copy.deepcopy(collector.get("candidate"))
        if not candidate:
            return platform_error(request, "CANDIDATE_RULE_NOT_FOUND", "请先探索并生成候选规则", 409)
        if not _valid_selector(body.get("listSelector")):
            return platform_error(
                request,
                "VALIDATION_FAILED",
                "listSelector 必须是有效的 css: 或 jsonpath: selector",
                422,
                pointer="/listSelector",
            )
        pagination = _normalize_candidate_pagination(body.get("pagination"))
        if pagination is None:
            return platform_error(request, "VALIDATION_FAILED", "pagination 与候选规则合同不一致", 422, pointer="/pagination")
        mode = candidate["mode"]
        detail_link_selector = body.get("detailLinkSelector")
        if mode == "single" and (detail_link_selector is not None or pagination["type"] != "none"):
            return platform_error(request, "VALIDATION_FAILED", "单阶段规则不能配置详情链接或分页", 422)
        if mode == "list_detail" and (not _valid_selector(detail_link_selector) or pagination["type"] == "none"):
            return platform_error(request, "VALIDATION_FAILED", "两阶段规则必须配置详情链接与分页", 422)

        field_inputs = body.get("fields")
        expected_keys = [field["key"] for field in candidate["fields"]]
        if not isinstance(field_inputs, list) or len(field_inputs) != len(expected_keys):
            return platform_error(request, "VALIDATION_FAILED", "fields 必须完整覆盖候选输出字段", 422, pointer="/fields")
        selectors: dict[str, str] = {}
        for index, field in enumerate(field_inputs):
            if not isinstance(field, dict) or set(field) != {"key", "selector"}:
                return platform_error(request, "VALIDATION_FAILED", "字段编辑项与合同不一致", 422, pointer=f"/fields/{index}")
            key = field.get("key")
            selector = field.get("selector")
            if key in selectors or key not in expected_keys or not _valid_selector(selector):
                return platform_error(request, "VALIDATION_FAILED", "字段 key 或 selector 无效", 422, pointer=f"/fields/{index}")
            selectors[key] = selector
        if set(selectors) != set(expected_keys):
            return platform_error(request, "VALIDATION_FAILED", "fields 必须完整覆盖候选输出字段", 422, pointer="/fields")

        spec = copy.deepcopy(candidate["gatherSpec"])
        list_field_inputs = body.get("listFields")
        if mode == "list_detail" and list_field_inputs is not None:
            expected_list_keys = list(spec["collect"]["list"]["fields"])
            if not isinstance(list_field_inputs, list) or len(list_field_inputs) != len(expected_list_keys):
                return platform_error(
                    request,
                    "VALIDATION_FAILED",
                    "listFields 必须完整覆盖列表阶段字段",
                    422,
                    pointer="/listFields",
                )
            list_selectors: dict[str, str] = {}
            for index, field in enumerate(list_field_inputs):
                if not isinstance(field, dict) or set(field) != {"key", "selector"}:
                    return platform_error(
                        request,
                        "VALIDATION_FAILED",
                        "列表字段编辑项与合同不一致",
                        422,
                        pointer=f"/listFields/{index}",
                    )
                key = field.get("key")
                selector = field.get("selector")
                if key in list_selectors or key not in expected_list_keys or not _valid_selector(selector):
                    return platform_error(
                        request,
                        "VALIDATION_FAILED",
                        "列表字段 key 或 selector 无效",
                        422,
                        pointer=f"/listFields/{index}",
                    )
                list_selectors[key] = selector
            if set(list_selectors) != set(expected_list_keys):
                return platform_error(
                    request,
                    "VALIDATION_FAILED",
                    "listFields 必须完整覆盖列表阶段字段",
                    422,
                    pointer="/listFields",
                )
            if list_selectors.get("detailUrl") != detail_link_selector:
                return platform_error(
                    request,
                    "VALIDATION_FAILED",
                    "listFields.detailUrl 必须与 detailLinkSelector 一致",
                    422,
                    pointer="/listFields",
                )
            for key, selector in list_selectors.items():
                spec["collect"]["list"]["fields"][key]["selector"] = selector
        spec["collect"]["list"]["itemsSelector"] = body["listSelector"]
        spec_pagination = dict(pagination)
        if spec_pagination["type"] == "page":
            spec_pagination["location"] = "query"
        spec["collect"]["list"]["pagination"] = spec_pagination
        spec["collect"]["budget"]["maxPages"] = pagination.get("maxPages", 1)
        if mode == "list_detail":
            spec["collect"]["list"]["fields"]["detailUrl"]["selector"] = detail_link_selector
            output_fields = spec["collect"]["detail"]["fields"]
        else:
            output_fields = spec["collect"]["list"]["fields"]
        for key, selector in selectors.items():
            output_fields[key]["selector"] = selector
        override = {
            "overrideId": stable_id("override", uuid.uuid4().hex),
            "digest": digest_value(body),
        }
        spec["compiler"]["overrideRefs"] = [*spec["compiler"].get("overrideRefs", []), override]
        spec["compiler"]["compiledAt"] = datetime.now().astimezone().isoformat()
        spec["integrity"]["ruleDigest"] = calculate_rule_digest(spec)
        try:
            contracts.validate_gather_spec(spec)
        except Exception as exc:  # noqa: BLE001
            return platform_error(request, "VALIDATION_FAILED", f"候选 GatherSpec 校验失败：{exc}", 422, pointer="/candidateRule")

        candidate.update(
            id=stable_id("candidate", uuid.uuid4().hex),
            digest=digest_value(spec),
            listSelector=body["listSelector"],
            detailLinkSelector=detail_link_selector,
            pagination=pagination,
            gatherSpec=spec,
        )
        for field in candidate["fields"]:
            field["selector"] = selectors[field["key"]]
        try:
            preview_items = _validate_candidate_against_latest_samples(collector, candidate)
        except Exception as exc:  # noqa: BLE001
            return platform_error(
                request,
                "CANDIDATE_VALIDATION_FAILED",
                str(exc),
                422,
                pointer="/candidateRule",
            )
        collector.update(
            status="ready_review",
            candidate=candidate,
            previewItems=preview_items,
            reviewDecisions=None,
            updatedAt="刚刚",
        )
        store.save_collector(collector)
        remember(scope, idempotency_key, body, 200, collector)
        return collector


@app.post("/api/v1/collectors/{collector_id}/collection-policy")
async def save_collection_policy(
    collector_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    required = {"mode", "initialWindowDays", "lookbackDays", "consecutiveOlderPages", "maxPages", "maxItems", "timezone"}
    body, body_error = await read_contract_body(request, required=required)
    if body_error:
        return body_error
    with mutation_lock:
        scope = f"POST:/collectors/{collector_id}/collection-policy"
        if found := replay(scope, idempotency_key, body, request):
            return found
        collector = store.get_collector(collector_id)
        if not collector:
            return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
        if collector.get("activeOperationId") or store.has_active_run(collector_id):
            return platform_error(request, "OPERATION_ALREADY_ACTIVE", "异步任务运行期间不能修改采集范围", 409)
        try:
            updated = store.create_collection_policy(collector_id, body)
        except ValueError as exc:
            return platform_error(request, "VALIDATION_FAILED", str(exc), 422, pointer="/collectionPolicy")
        remember(scope, idempotency_key, body, 200, updated)
        return updated


@app.put("/api/v1/collectors/{collector_id}/schedule")
async def update_collector_schedule(
    collector_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    required = {"enabled", "cronExpression", "timezone", "overlapPolicy"}
    body, body_error = await read_contract_body(request, required=required)
    if body_error:
        return body_error
    with mutation_lock:
        scope = f"PUT:/collectors/{collector_id}/schedule"
        if found := replay(scope, idempotency_key, body, request):
            return found
        collector = store.get_collector(collector_id)
        if not collector:
            return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
        try:
            updated = store.save_schedule(collector_id, body)
        except ValueError as exc:
            return platform_error(request, "VALIDATION_FAILED", str(exc), 422, pointer="/schedule")
        remember(scope, idempotency_key, body, 200, updated)
        return updated


@app.post("/api/v1/collectors", status_code=201)
async def create_collector(request: Request, response: Response, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required={"name", "intent", "sourceUrl"})
    if body_error:
        return body_error
    scope = "POST:/collectors"
    if found := replay(scope, idempotency_key, body, request):
        return found
    try:
        source_url, source_host = normalize_source_url(
            body.get("sourceUrl", ""),
            allow_http_localhost=settings.allow_http_localhost,
            allow_http_public=settings.allow_http_public,
        )
    except SourceUrlError as exc:
        return platform_error(request, exc.code, str(exc), 422, pointer="/sourceUrl")
    if store.source_exists(source_url):
        return platform_error(request, "SOURCE_ALREADY_EXISTS", "该 Source URL 已存在", 409, pointer="/sourceUrl")
    if not str(body.get("name", "")).strip() or not str(body.get("intent", "")).strip():
        return platform_error(request, "VALIDATION_FAILED", "name 与 intent 不能为空", 422)
    collection_name = body["name"].strip()
    collector = store.create_collector(
        collection_name,
        body["intent"].strip(),
        source_url,
        source_host,
        collection_id=stable_id("collection", uuid.uuid4().hex, 40),
        collection_name=collection_name,
    )
    response.headers["Location"] = f"/api/v1/collectors/{collector['id']}"
    remember(scope, idempotency_key, body, 201, collector)
    return collector


@app.post("/api/v1/collectors/batch")
async def create_collectors_batch(request: Request, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(
        request,
        required={"collectionName", "intent", "sourceUrls"},
        optional={"collectionId"},
    )
    if body_error:
        return body_error
    scope = "POST:/collectors/batch"
    if found := replay(scope, idempotency_key, body, request):
        return found
    urls = body.get("sourceUrls") or []
    if not str(body.get("collectionName", "")).strip() or not str(body.get("intent", "")).strip():
        return platform_error(request, "VALIDATION_FAILED", "collectionName 与 intent 不能为空", 422)
    if not isinstance(urls, list) or not 1 <= len(urls) <= 1000:
        return platform_error(request, "VALIDATION_FAILED", "sourceUrls 必须包含 1 至 1000 个网址", 422, pointer="/sourceUrls")
    requested_collection_id = str(body.get("collectionId", "")).strip()
    collection_name = str(body.get("collectionName", "")).strip()
    intent = str(body.get("intent", "")).strip()
    collection_version = "tender_notice_v4"
    if requested_collection_id:
        reference = next((item for item in store.list_collectors() if item.get("collectionId") == requested_collection_id), None)
        if reference is None:
            return platform_error(request, "COLLECTION_NOT_FOUND", "采集需求不存在", 404, pointer="/collectionId")
        collection_id = requested_collection_id
        collection_name = reference["collectionName"]
        intent = reference["intent"]
        collection_version = reference["collectionVersion"]
    else:
        collection_id = stable_id("collection", f"{collection_name}_{uuid.uuid4().hex[:12]}", 40)
    seen: set[str] = set()
    results = []
    for index, raw in enumerate(urls):
        try:
            source_url, source_host = normalize_source_url(
                str(raw),
                allow_http_localhost=settings.allow_http_localhost,
                allow_http_public=settings.allow_http_public,
            )
            if source_url in seen:
                raise SourceUrlError("DUPLICATE_IN_BATCH", "批次内 URL 重复")
            seen.add(source_url)
            if store.source_exists(source_url):
                raise SourceUrlError("SOURCE_ALREADY_EXISTS", "该 Source URL 已存在")
            name = source_host
            collector = store.create_collector(
                name,
                intent,
                source_url,
                source_host,
                collection_id=collection_id,
                collection_name=collection_name,
                collection_version=collection_version,
            )
            results.append({"sourceUrl": str(raw).strip(), "status": "created", "collector": collector, "error": None})
        except SourceUrlError as exc:
            results.append(
                {
                    "sourceUrl": str(raw).strip(),
                    "status": "rejected",
                    "collector": None,
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "requestId": request.state.request_id,
                        "retryable": False,
                        "pointer": f"/sourceUrls/{index}",
                        "details": {},
                    },
                }
            )
    created = sum(item["status"] == "created" for item in results)
    value = {
        "collectionId": collection_id,
        "collectionName": collection_name,
        "collectionVersion": collection_version,
        "total": len(results),
        "createdCount": created,
        "rejectedCount": len(results) - created,
        "results": results,
    }
    remember(scope, idempotency_key, body, 200, value)
    return value


@app.post("/api/v1/collectors/{collector_id}/explorations", status_code=202)
def start_exploration(
    collector_id: str,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    with mutation_lock:
        return _start_exploration(collector_id, request, response, idempotency_key)


def _start_exploration(collector_id: str, request: Request, response: Response, idempotency_key: str | None):
    if error := require_idempotency(request, idempotency_key):
        return error
    body = {"collectorId": collector_id}
    scope = f"POST:/collectors/{collector_id}/explorations"
    if found := replay(scope, idempotency_key, body, request):
        return found
    collector = store.get_collector(collector_id)
    if not collector:
        return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    if collector["activeOperationId"]:
        active = store.get_operation(collector["activeOperationId"])
        if active and active["status"] not in TERMINAL:
            return platform_error(request, "OPERATION_ALREADY_ACTIVE", "Collector 已有进行中的异步任务", 409)
    ai_run_id = stable_id("ai_run", uuid.uuid4().hex, 32)
    trigger = "regeneration" if collector.get("activeRuleVersion") or collector.get("candidate") else "initial_generation"
    operation = store.create_async_command(
        kind="explore",
        collector_id=collector_id,
        resource_type="collector",
        resource_id=collector_id,
        job_payload={"collectorId": collector_id, "previousStatus": collector["status"], "aiRunId": ai_run_id},
        collector_changes={"status": "exploring", "updatedAt": "刚刚"},
        ai_run={
            "id": ai_run_id,
            "collectorId": collector_id,
            "collectorName": collector["name"],
            "sourceUrl": collector["sourceUrl"],
            "kind": "rule_generation",
            "trigger": trigger,
            "initiatedBy": request.state.auth_user["id"] if request.state.auth_user else "system",
        },
    )
    response.headers["Location"] = operation["statusUrl"]
    remember(scope, idempotency_key, body, 202, operation)
    return operation


@app.get("/api/v1/operations/{operation_id}")
def get_operation(operation_id: str, request: Request, response: Response):
    operation = store.get_operation(operation_id)
    if not operation:
        return platform_error(request, "OPERATION_NOT_FOUND", "Operation 不存在", 404)
    response.headers["Retry-After"] = str(max(0, operation["pollAfterMs"] // 1000))
    return operation


@app.get("/api/v1/ai-runs")
def list_ai_runs(limit: int = 50, collector_id: str | None = Query(None, alias="collectorId")):
    return page(store.list_ai_runs(collector_id), limit)


@app.get("/api/v1/ai-runs/{ai_run_id}")
def get_ai_run(ai_run_id: str, request: Request):
    ai_run = store.get_ai_run(ai_run_id)
    return ai_run if ai_run else platform_error(request, "AI_RUN_NOT_FOUND", "AI 任务不存在", 404)


@app.post("/api/v1/collectors/{collector_id}/publish")
async def publish_rule(collector_id: str, request: Request, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required={"reviewDecisions"})
    if body_error:
        return body_error
    with mutation_lock:
        return _publish_rule(collector_id, request, idempotency_key, body)


def _publish_rule(collector_id: str, request: Request, idempotency_key: str, body: dict[str, Any]):
    scope = f"POST:/collectors/{collector_id}/publish"
    if found := replay(scope, idempotency_key, body, request):
        return found
    collector = store.get_collector(collector_id)
    if not collector:
        return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    fields = (collector.get("candidate") or {}).get("fields", [])
    decisions = body.get("reviewDecisions") or {}
    invalid = []
    for field in fields:
        decision = decisions.get(field["key"])
        valid = decision in ALLOWED_REVIEW_DECISIONS
        valid = valid and (not field["required"] or decision == "approved")
        valid = valid and (not field["warning"] or decision in {"risk_accepted", "excluded"})
        if not valid:
            invalid.append(field["key"])
    if collector["status"] != "ready_review" or not fields or invalid:
        return platform_error(
            request,
            "REVIEW_DECISION_INVALID",
            "每个候选字段都必须具有有效的审核决定",
            409,
            pointer=f"/reviewDecisions/{invalid[0]}" if invalid else "/reviewDecisions",
        )
    version_match = re.search(r"(\d+)$", collector.get("activeRuleVersion") or "0")
    current = int(version_match.group(1)) if version_match else 0
    try:
        published = persist_published_rule(
            collector,
            rule_version_id=next_rule_version_id(collector_id, current + 1),
            review_decisions=decisions,
            request_id=request.state.request_id,
            actor_id=request.state.auth_user["id"],
        )
    except IntegrityError as exc:
        return platform_error(request, exc.code, str(exc), 409)
    remember(scope, idempotency_key, body, 200, published)
    return published


class RunStartError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def create_run_operation(collector_id: str) -> dict[str, Any]:
    collector = store.get_collector(collector_id)
    if not collector:
        raise RunStartError("COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    if collector["status"] != "published" or not collector["activeRuleVersion"]:
        raise RunStartError("RULE_NOT_PUBLISHED", "Collector 没有可执行的已发布规则")
    try:
        integrity = verified_run_integrity(collector)
    except IntegrityError as exc:
        raise RunStartError(exc.code, str(exc)) from exc
    if store.has_active_run(collector_id):
        raise RunStartError("RUN_ALREADY_ACTIVE", "Collector 已有进行中的 Run")
    collector = store.ensure_collection_policy(collector_id)
    policy = collector["collectionPolicy"]
    checkpoint = store.get_checkpoint(collector_id)
    if checkpoint and checkpoint.get("policyVersionId") == policy["id"]:
        execution_mode = "incremental"
        checkpoint_before = copy.deepcopy(checkpoint)
        window_start = datetime.fromisoformat(checkpoint["watermark"]).date() - timedelta(days=policy["lookbackDays"])
    else:
        execution_mode = "initial"
        checkpoint_before = None
        local_today = datetime.now(ZoneInfo(policy["timezone"])).date()
        window_start = local_today - timedelta(days=policy["initialWindowDays"])
    run_id = stable_id("run", uuid.uuid4().hex)
    run = {
        "id": run_id,
        "operationId": None,
        "collectorId": collector_id,
        "collectorName": collector["name"],
        "collectionMode": collector["candidate"]["mode"],
        "status": "queued",
        "startedAt": "刚刚",
        "duration": "—",
        "acceptedCount": 0,
        "rejectedCount": 0,
        "pagesFetched": 0,
        "listPagesFetched": 0,
        "detailUrlsDiscovered": 0,
        "detailPagesFetched": 0,
        "recordsOutsideWindow": 0,
        "duplicateDetailUrls": 0,
        "newItems": 0,
        "updatedItems": 0,
        "unchangedItems": 0,
        "paginationStopReason": "not_applicable",
        "ruleVersion": collector["activeRuleVersion"],
        "ruleDigest": integrity["ruleDigest"],
        "ruleAttestationId": integrity["attestationId"],
        "signingKeyId": integrity["keyId"],
        "trustRevision": integrity["trustRevision"],
        "integrityStatus": "verified",
        "policyContextStatus": "fixed",
        "policyVersion": policy["id"],
        "policyDigest": policy["digest"],
        "executionMode": execution_mode,
        "windowStart": window_start.isoformat(),
        "checkpointBefore": checkpoint_before,
        "checkpointAfter": None,
        "artifactMode": "sampled",
        "summary": "等待 Crawlee Worker 执行。",
        "recoveryAction": "无需操作。",
        "items": [],
    }
    operation = store.create_async_command(
        kind="run",
        collector_id=collector_id,
        resource_type="run",
        resource_id=run_id,
        job_payload={
            "collectorId": collector_id,
            "runId": run_id,
            "integrity": integrity,
            "policyVersionId": policy["id"],
            "policyDigest": policy["digest"],
            "checkpointBefore": checkpoint_before,
        },
        run=run,
    )
    return operation


@app.post("/api/v1/collectors/{collector_id}/runs", status_code=202)
def start_run(collector_id: str, request: Request, response: Response, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    with mutation_lock:
        return _start_run(collector_id, request, response, idempotency_key)


def _start_run(collector_id: str, request: Request, response: Response, idempotency_key: str | None):
    if error := require_idempotency(request, idempotency_key):
        return error
    body = {"collectorId": collector_id}
    scope = f"POST:/collectors/{collector_id}/runs"
    if found := replay(scope, idempotency_key, body, request):
        return found
    try:
        operation = create_run_operation(collector_id)
    except RunStartError as exc:
        return platform_error(request, exc.code, str(exc), exc.status_code)
    response.headers["Location"] = operation["statusUrl"]
    remember(scope, idempotency_key, body, 202, operation)
    return operation


@app.get("/api/v1/runs")
def list_runs(limit: int = 50):
    return page(store.list_runs(), limit)


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, request: Request):
    run = store.get_run(run_id)
    return run if run else platform_error(request, "RUN_NOT_FOUND", "Run 不存在", 404)


EXPORT_CSV_COLUMNS = (
    "entityKey",
    "revision",
    "decision",
    "changeType",
    "collectorName",
    "sourceHost",
    "sourceUrl",
    "publishedAt",
    "observedAt",
)


def invalid_cursor_error(request: Request) -> JSONResponse:
    return platform_error(request, "INVALID_CURSOR", "Cursor 无效，请使用上一页响应返回的 nextCursor", 400)


def sink_view(sink: dict[str, Any]) -> dict[str, Any]:
    """API projection of a stored sink; the secret itself never leaves the store."""
    return {
        "id": sink["id"],
        "collectorId": sink["collectorId"],
        "type": sink["type"],
        "url": sink["url"],
        "enabled": bool(sink["enabled"]),
        "version": int(sink["version"]),
        "credentialConfigured": bool(sink["secretConfigured"]),
        "createdAt": sink["createdAt"],
        "updatedAt": sink["updatedAt"],
    }


def delivery_view(delivery: dict[str, Any]) -> dict[str, Any]:
    """API projection of a delivery; synthetic sink-test deliveries carry kind=test."""
    view = {key: value for key, value in delivery.items() if key != "secretEncrypted"}
    if str(view.get("itemEventId", "")).startswith("test_"):
        view["kind"] = "test"
    return view


def sink_url_error(value: Any) -> str | None:
    """Return a stable rejection message when the sink URL is not a plain http(s) URL."""
    if not isinstance(value, str) or not value.strip():
        return "Sink URL 不能为空"
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Sink URL 仅支持 HTTP 或 HTTPS"
    if parsed.username or parsed.password:
        return "Sink URL 不能嵌入用户名或密码"
    return None


def sink_not_found(request: Request) -> JSONResponse:
    return platform_error(request, "SINK_NOT_FOUND", "Sink 不存在", 404)


def get_collector_sink(collector_id: str, sink_id: str) -> dict[str, Any] | None:
    sink = store.get_sink(sink_id)
    if sink is None or sink["collectorId"] != collector_id:
        return None
    return sink


def export_csv_row(item: dict[str, Any], extracted_columns: list[str]) -> list[Any]:
    row = [item.get(column) for column in EXPORT_CSV_COLUMNS]
    extracted = item.get("extractedData")
    extracted = extracted if isinstance(extracted, dict) else {}
    for column in extracted_columns:
        value = extracted.get(column)
        if value is None or isinstance(value, str):
            row.append(value)
        else:
            row.append(json.dumps(value, ensure_ascii=False))
    return row


def iter_export_csv(
    filters: dict[str, Any],
    columns: list[str],
) -> Iterator[str]:
    yield "\ufeff"
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    yield buffer.getvalue()
    for item in store.iter_items_export(**filters):
        buffer.seek(0)
        buffer.truncate()
        writer.writerow(export_csv_row(item, columns[len(EXPORT_CSV_COLUMNS):]))
        yield buffer.getvalue()


def iter_export_jsonl(filters: dict[str, Any]) -> Iterator[str]:
    for item in store.iter_items_export(**filters):
        yield json.dumps(item, ensure_ascii=False) + "\n"


@app.get("/api/v1/items")
def list_items(request: Request, limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None)):
    try:
        result = store.list_items_cursor(limit=limit, cursor=cursor)
    except InvalidCursor:
        return invalid_cursor_error(request)
    next_cursor = result["nextCursor"]
    return {"items": result["items"], "page": {"nextCursor": next_cursor}, "nextCursor": next_cursor}


@app.get("/api/v1/items/export")
def export_items(
    request: Request,
    format: str = Query(..., pattern="^(csv|jsonl)$"),
    collector_id: str | None = Query(None, alias="collectorId"),
    run_id: str | None = Query(None, alias="runId"),
    decision: str | None = Query(None),
    entity_key: str | None = Query(None, alias="entityKey"),
):
    filters = {"collector_id": collector_id, "run_id": run_id, "decision": decision, "entity_key": entity_key}
    probe = store.iter_items_export(**filters)
    count = 0
    extracted_columns: set[str] = set()
    try:
        for item in probe:
            count += 1
            if count > EXPORT_ITEMS_CAP:
                return platform_error(request, "EXPORT_TOO_LARGE", "导出范围超过单次导出上限，请缩小过滤条件后重试", 400)
            extracted = item.get("extractedData")
            if isinstance(extracted, dict):
                extracted_columns.update(str(key) for key in extracted)
    finally:
        probe.close()

    if format == "csv":
        columns = [*EXPORT_CSV_COLUMNS, *sorted(extracted_columns)]
        return StreamingResponse(
            iter_export_csv(filters, columns),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="extrio-items.csv"'},
        )
    return StreamingResponse(
        iter_export_jsonl(filters),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="extrio-items.jsonl"'},
    )


@app.get("/api/v1/items/{item_id}")
def get_item(item_id: str, request: Request):
    item = store.get_item(item_id)
    return item if item else platform_error(request, "ITEM_NOT_FOUND", "Item 或拒绝候选不存在", 404)


@app.get("/api/v1/collectors/{collector_id}/sinks")
def list_sinks(collector_id: str, request: Request):
    if store.get_collector(collector_id) is None:
        return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    sinks = [sink_view(sink) for sink in store.list_sinks_for_collector(collector_id)]
    return {"items": sinks, "page": {"nextCursor": None}}


@app.post("/api/v1/collectors/{collector_id}/sinks", status_code=201)
async def create_sink(
    collector_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required={"url"}, optional={"type", "secret", "enabled"})
    if body_error:
        return body_error
    scope = f"POST:/collectors/{collector_id}/sinks"
    if found := replay(scope, idempotency_key, body, request):
        return found
    if store.get_collector(collector_id) is None:
        return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    sink_type = str(body.get("type") or "webhook")
    if sink_type != "webhook":
        return platform_error(request, "VALIDATION_FAILED", "当前仅支持 webhook Sink", 422, pointer="/type")
    if url_error := sink_url_error(body.get("url")):
        return platform_error(request, "INVALID_URL", url_error, 400, pointer="/url")
    enabled = body.get("enabled", True)
    if not isinstance(enabled, bool):
        return platform_error(request, "VALIDATION_FAILED", "enabled 必须是布尔值", 422, pointer="/enabled")
    secret = body.get("secret")
    if secret is not None and (not isinstance(secret, str) or not secret.strip()):
        return platform_error(request, "VALIDATION_FAILED", "secret 必须是非空字符串", 422, pointer="/secret")
    sink = store.create_sink(
        collector_id,
        cipher=credential_cipher,
        url=str(body["url"]).strip(),
        secret=secret,
        enabled=enabled,
        sink_type=sink_type,
    )
    value = sink_view(sink)
    remember(scope, idempotency_key, body, 201, value)
    return value


@app.put("/api/v1/collectors/{collector_id}/sinks/{sink_id}")
async def update_sink(
    collector_id: str,
    sink_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    body, body_error = await read_contract_body(request, required=set(), optional={"url", "secret", "enabled"})
    if body_error:
        return body_error
    scope = f"PUT:/collectors/{collector_id}/sinks/{sink_id}"
    if found := replay(scope, idempotency_key, body, request):
        return found
    if get_collector_sink(collector_id, sink_id) is None:
        return sink_not_found(request)
    url = None
    if "url" in body:
        if url_error := sink_url_error(body.get("url")):
            return platform_error(request, "INVALID_URL", url_error, 400, pointer="/url")
        url = str(body["url"]).strip()
    enabled = body.get("enabled") if "enabled" in body else None
    if enabled is not None and not isinstance(enabled, bool):
        return platform_error(request, "VALIDATION_FAILED", "enabled 必须是布尔值", 422, pointer="/enabled")
    secret = body.get("secret") if "secret" in body else None
    if secret is not None and (not isinstance(secret, str) or not secret.strip()):
        return platform_error(request, "VALIDATION_FAILED", "secret 必须是非空字符串", 422, pointer="/secret")
    updated = store.update_sink(sink_id, cipher=credential_cipher, url=url, secret=secret, enabled=enabled)
    value = sink_view(updated)
    remember(scope, idempotency_key, body, 200, value)
    return value


@app.delete("/api/v1/collectors/{collector_id}/sinks/{sink_id}", status_code=204)
async def delete_sink(
    collector_id: str,
    sink_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    body = {"collectorId": collector_id, "sinkId": sink_id}
    scope = f"DELETE:/collectors/{collector_id}/sinks/{sink_id}"
    try:
        replayed = store.idempotency_replay(scope, idempotency_key, body)
    except IdempotencyConflict:
        return platform_error(request, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key 已被不同请求占用", 409)
    if replayed is not None:
        return Response(status_code=204, headers={"Idempotency-Replayed": "true"})
    if get_collector_sink(collector_id, sink_id) is None:
        return sink_not_found(request)
    store.delete_sink(sink_id)
    store.remember_idempotency(scope, idempotency_key, body, 204, {})
    return Response(status_code=204)


@app.post("/api/v1/collectors/{collector_id}/sinks/{sink_id}/test", status_code=202)
def test_sink(
    collector_id: str,
    sink_id: str,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    body = {"collectorId": collector_id, "sinkId": sink_id}
    scope = f"POST:/collectors/{collector_id}/sinks/{sink_id}/test"
    if found := replay(scope, idempotency_key, body, request):
        return found
    if store.get_collector(collector_id) is None:
        return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    if get_collector_sink(collector_id, sink_id) is None:
        return sink_not_found(request)
    delivery = store.enqueue_delivery(
        collector_id=collector_id,
        sink_id=sink_id,
        item_event_id=f"test_{uuid.uuid4().hex}",
    )
    value = delivery_view(delivery)
    response.headers["Location"] = f"/api/v1/deliveries/{delivery['id']}"
    remember(scope, idempotency_key, body, 202, value)
    return value


@app.get("/api/v1/collectors/{collector_id}/deliveries")
def list_deliveries(collector_id: str, request: Request):
    if store.get_collector(collector_id) is None:
        return platform_error(request, "COLLECTOR_NOT_FOUND", "Collector 不存在", 404)
    items = []
    for delivery in store.list_deliveries_for_collector(collector_id):
        attempts = store.list_delivery_attempts(delivery["id"])
        items.append({**delivery_view(delivery), "latestAttempt": attempts[-1] if attempts else None})
    return {"items": items, "page": {"nextCursor": None}}


@app.get("/api/v1/deliveries/{delivery_id}")
def get_delivery(delivery_id: str, request: Request):
    delivery = store.get_delivery(delivery_id)
    if delivery is None:
        return platform_error(request, "DELIVERY_NOT_FOUND", "Delivery 不存在", 404)
    return {**delivery_view(delivery), "attempts": store.list_delivery_attempts(delivery_id)}


@app.post("/api/v1/deliveries/{delivery_id}/redeliver")
def redeliver_delivery(
    delivery_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if error := require_idempotency(request, idempotency_key):
        return error
    body = {"deliveryId": delivery_id}
    scope = f"POST:/deliveries/{delivery_id}/redeliver"
    if found := replay(scope, idempotency_key, body, request):
        return found
    delivery = store.get_delivery(delivery_id)
    if delivery is None:
        return platform_error(request, "DELIVERY_NOT_FOUND", "Delivery 不存在", 404)
    try:
        redelivered = store.redeliver_delivery(delivery_id)
    except ValueError:
        return platform_error(request, "DELIVERY_IN_FLIGHT", "Delivery 正在投递中，请等待租约过期后再重试", 409)
    value = delivery_view(redelivered)
    remember(scope, idempotency_key, body, 200, value)
    return value


def custom_openapi():
    return contracts.openapi


app.openapi = custom_openapi


def run() -> None:
    uvicorn.run("extrio.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
