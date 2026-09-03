import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from pwdlib import PasswordHash

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256

ROLE_ADMINISTRATOR = "administrator"
ROLE_ENGINEER = "engineer"
ROLE_REVIEWER = "reviewer"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMINISTRATOR, ROLE_ENGINEER, ROLE_REVIEWER, ROLE_VIEWER)

password_hash = PasswordHash.recommended()
_dummy_password_hash = password_hash.hash(secrets.token_urlsafe(24))
_login_storage = MemoryStorage()
_login_limiter = MovingWindowRateLimiter(_login_storage)


def validate_username(value: object) -> str:
    username = str(value or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("用户名须为 3 至 64 位字母、数字、点、短横线或下划线")
    return username


def validate_password(value: object) -> str:
    password = str(value or "")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"密码长度须为 {MIN_PASSWORD_LENGTH} 至 {MAX_PASSWORD_LENGTH} 个字符")
    return password


def validate_display_name(value: object, username: str) -> str:
    display_name = str(value or "").strip() or username
    if not 1 <= len(display_name) <= 64:
        raise ValueError("显示名称须为 1 至 64 个字符")
    return display_name


def validate_role(value: object) -> str:
    role = str(value or "").strip()
    if role not in ROLES:
        raise ValueError("角色必须是 administrator、engineer、reviewer 或 viewer")
    return role


def hash_password(value: str) -> str:
    return password_hash.hash(value)


def verify_password(value: str, encoded: str | None) -> bool:
    candidate_hash = encoded or _dummy_password_hash
    try:
        valid = password_hash.verify(value, candidate_hash)
    except Exception:  # malformed persisted hashes must not bypass generic login failure
        valid = False
    return bool(valid and encoded)


def new_session(hours: int) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return token, session_token_hash(token), expires_at


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def allow_login(key: str, limit: str) -> bool:
    return _login_limiter.hit(parse(limit), key)


def reset_login_limits() -> None:
    _login_storage.reset()
