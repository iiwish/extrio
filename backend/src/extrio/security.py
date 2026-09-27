import ipaddress
from urllib.parse import urlsplit, urlunsplit


class SourceUrlError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def trusted_client_identity(remote_host: str, forwarded_for: str, trusted_proxy_count: int) -> str:
    """Resolve a login identity only through explicitly trusted proxy hops."""

    if trusted_proxy_count <= 0:
        return remote_host or "unknown"
    candidates = [value.strip() for value in forwarded_for.split(",") if value.strip()]
    if not candidates:
        return remote_host or "unknown"
    index = min(trusted_proxy_count, len(candidates)) - 1
    candidate = candidates[-index - 1] if index >= 0 else candidates[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return remote_host or "unknown"


def normalize_source_url(
    value: str,
    *,
    allow_http_localhost: bool = False,
    allow_http_public: bool = False,
    has_access_profile: bool = False,
) -> tuple[str, str]:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise SourceUrlError("INVALID_URL", "网址格式无效") from exc

    if not host or parsed.username or parsed.password or parsed.fragment:
        raise SourceUrlError("INVALID_URL", "网址必须包含有效主机，且不能包含凭据或片段")

    is_loopback = host == "localhost"
    address = None
    try:
        address = ipaddress.ip_address(host)
        is_loopback = is_loopback or address.is_loopback
    except ValueError:
        pass

    if parsed.scheme not in {"http", "https"}:
        raise SourceUrlError("INVALID_URL", "来源网址仅支持 HTTP 或 HTTPS")
    if parsed.scheme == "http" and has_access_profile:
        raise SourceUrlError("HTTPS_REQUIRED", "配置 AccessProfile 或凭据的来源必须使用 HTTPS")
    http_is_allowed = allow_http_public or (allow_http_localhost and is_loopback)
    if parsed.scheme == "http" and not http_is_allowed:
        raise SourceUrlError(
            "HTTPS_REQUIRED",
            "当前部署未允许匿名 HTTP 来源，请改用 HTTPS；仅在部署配置明确允许时可在 设置 → 采集策略 中启用",
        )
    if is_loopback and not allow_http_localhost:
        raise SourceUrlError("INVALID_URL", "来源网址不能指向私有、保留或 link-local 网络")
    if address and (address.is_private or address.is_link_local or address.is_reserved) and not (allow_http_localhost and is_loopback):
        raise SourceUrlError("INVALID_URL", "来源网址不能指向私有、保留或 link-local 网络")

    netloc = host
    if port is not None:
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme, netloc, path, parsed.query, "")), host
