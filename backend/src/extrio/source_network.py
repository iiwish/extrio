"""Anonymous source egress shared by HTTP crawling and restricted Chromium."""

import asyncio
import ipaddress
import socket
import ssl
import zlib
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx


class SourceNetworkError(RuntimeError):
    code = "SOURCE_NETWORK_REJECTED"
    retryable = False


def _bad_ecpoint(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLError) and getattr(exc, "reason", None) == "BAD_ECPOINT":
            return True
        exc = exc.__cause__ or exc.__context__
    return False


@dataclass
class FetchBudget:
    max_total_bytes: int = 50_000_000
    max_page_bytes: int = 5_000_000
    max_seconds: float = 180
    total_bytes: int = 0


@dataclass
class SourceResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes

    def require_success(self) -> "SourceResponse":
        if self.status in {401, 403}:
            raise SourceNetworkError("authentication_or_access_required")
        if not 200 <= self.status < 300:
            raise SourceNetworkError(f"http_status_{self.status}")
        return self


class SourceNetwork:
    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        allow_localhost: bool = False,
        allow_http: bool = True,
        budget: FetchBudget | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_redirects: int = 5,
        request_timeout: float = 30,
        max_concurrency: int = 4,
        requests_per_second: float | None = None,
        max_attempts: int = 3,
    ):
        self.allowed_hosts = {host.lower().rstrip(".") for host in allowed_hosts}
        self.allow_localhost = allow_localhost
        self.allow_http = allow_http
        self.budget = budget or FetchBudget()
        self.started = monotonic()
        self.transport = transport
        self.robots: dict[str, RobotFileParser] = {}
        self.final_urls: dict[str, str] = {}
        self.static_headers: dict[str, str] = {}
        self._tls_compatibility: dict[tuple[str, int | None], ssl.SSLContext] = {}
        self.max_redirects = max(0, min(max_redirects, 5))
        self.request_timeout = min(request_timeout, 30)
        self.max_attempts = max(1, min(max_attempts, 3))
        self.slots = asyncio.Semaphore(max(1, min(max_concurrency, 4)))
        self.rate_lock = asyncio.Lock()
        self.spacing = 1 / requests_per_second if requests_per_second else 0
        self.next_request_at = 0.0

    async def target(self, url: str) -> tuple[httpx.URL, str, str]:
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower().rstrip(".")
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as exc:
            raise SourceNetworkError("invalid_url") from exc
        if parts.scheme not in {"https", "http"} or not host or parts.username or parts.password:
            raise SourceNetworkError("invalid_url")
        if host not in self.allowed_hosts:
            raise SourceNetworkError("host_not_allowed")
        try:
            literal = ipaddress.ip_address(host)
            addresses = [str(literal)]
        except ValueError:
            try:
                records = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise SourceNetworkError("dns_resolution_failed") from exc
            addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses:
            raise SourceNetworkError("dns_resolution_failed")
        for address in addresses:
            parsed = ipaddress.ip_address(address)
            if not parsed.is_global and not (self.allow_localhost and parsed.is_loopback):
                raise SourceNetworkError("network_address_blocked")
        if parts.scheme == "http" and not self.allow_http:
            if not (self.allow_localhost and all(ipaddress.ip_address(ip).is_loopback for ip in addresses)):
                raise SourceNetworkError("https_required")
        original = httpx.URL(url)
        return original.copy_with(host=addresses[0], fragment=None), original.netloc.decode(), host

    async def fetch(self, url: str, *, follow_redirects: bool = True, respect_robots: bool = False) -> SourceResponse:
        remaining = self.budget.max_seconds - (monotonic() - self.started)
        if remaining <= 0:
            raise SourceNetworkError("duration_exceeded")
        try:
            async with asyncio.timeout(remaining):
                async with self.slots:
                    result = await self._fetch(url, follow_redirects=follow_redirects, respect_robots=respect_robots)
                self.final_urls[url] = result.url
                return result
        except TimeoutError as exc:
            raise SourceNetworkError("duration_exceeded") from exc
        except httpx.TimeoutException as exc:
            raise SourceNetworkError("source_request_timed_out") from exc
        except httpx.HTTPError as exc:
            raise SourceNetworkError("source_connection_failed") from exc

    async def _fetch(self, url: str, *, follow_redirects: bool, respect_robots: bool = False) -> SourceResponse:
        for _hop in range(self.max_redirects + 1):
            if respect_robots:
                await self.check_robots(url, within_slot=True)
            pinned_url, host_header, tls_name = await self.target(url)
            async with self.rate_lock:
                await asyncio.sleep(max(0, self.next_request_at - monotonic()))
                self.next_request_at = monotonic() + self.spacing
            try:
                async with asyncio.timeout(self.request_timeout):
                    result = await self._request(url, pinned_url, host_header, tls_name)
            except TimeoutError as exc:
                raise SourceNetworkError("source_request_timed_out") from exc
            if result.status not in {301, 302, 303, 307, 308}:
                return result
            location = result.headers.get("location")
            if not location:
                raise SourceNetworkError("redirect_missing_location")
            next_url = urljoin(url, location)
            if urlsplit(url).scheme == "https" and urlsplit(next_url).scheme != "https":
                raise SourceNetworkError("redirect_https_downgrade")
            await self.target(next_url)
            if not follow_redirects:
                if self.max_redirects == 0:
                    raise SourceNetworkError("redirect_limit_exceeded")
                result.headers["location"] = next_url
                return result
            url = next_url
        raise SourceNetworkError("redirect_limit_exceeded")

    async def _request(self, url, pinned_url, host_header, tls_name):
        peer = (tls_name, pinned_url.port)
        if pinned_url.scheme == "https" and peer in self._tls_compatibility:
            return await self._request_once(
                url, pinned_url, host_header, tls_name, verify=self._tls_compatibility[peer]
            )
        try:
            return await self._request_once(url, pinned_url, host_header, tls_name)
        except httpx.ConnectError as exc:
            if pinned_url.scheme != "https" or not _bad_ecpoint(exc):
                raise
        # Some legacy TLS peers mishandle OpenSSL's default group offer. Retry
        # only that handshake failure, retaining CA/hostname checks and pinning.
        context = httpx.create_ssl_context(verify=True, trust_env=False)
        context.minimum_version = max(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        context.set_ecdh_curve("prime256v1")
        result = await self._request_once(url, pinned_url, host_header, tls_name, verify=context)
        self._tls_compatibility[peer] = context
        return result

    async def _request_once(self, url, pinned_url, host_header, tls_name, *, verify=True):
        # No ambient proxies, cookies, user headers, or credentials cross this boundary.
        async with httpx.AsyncClient(
            transport=self.transport, trust_env=False, follow_redirects=False, timeout=self.request_timeout, verify=verify
        ) as client:
            async with client.stream(
                "GET",
                pinned_url,
                headers={**self.static_headers, "Host": host_header, "User-Agent": "Extrio/1.0", "Accept-Encoding": "identity"},
                extensions={"sni_hostname": tls_name},
            ) as response:
                headers = dict(response.headers)
                encoding = headers.get("content-encoding", "identity").lower()
                if encoding not in {"", "identity", "gzip", "deflate"}:
                    raise SourceNetworkError("encoded_response_unsupported")
                decoder = (
                    zlib.decompressobj(31 if encoding == "gzip" else 15)
                    if encoding in {"gzip", "deflate"} and not response.is_stream_consumed
                    else None
                )
                chunks = []
                size = 0
                stream = (
                    response.aiter_bytes(chunk_size=64 * 1024) if response.is_stream_consumed else response.aiter_raw(chunk_size=64 * 1024)
                )
                async for raw in stream:
                    limit = max(1, min(self.budget.max_page_bytes - size, self.budget.max_total_bytes - self.budget.total_bytes) + 1)
                    try:
                        chunk = decoder.decompress(raw, limit) if decoder else raw
                    except zlib.error as exc:
                        raise SourceNetworkError("invalid_content_encoding") from exc
                    size += len(chunk)
                    self.budget.total_bytes += len(chunk)
                    if size > self.budget.max_page_bytes:
                        raise SourceNetworkError("page_bytes_exceeded")
                    if self.budget.total_bytes > self.budget.max_total_bytes:
                        raise SourceNetworkError("total_bytes_exceeded")
                    chunks.append(chunk)
                if decoder and (not decoder.eof or decoder.unused_data):
                    raise SourceNetworkError("invalid_content_encoding")
                result = SourceResponse(url, response.status_code, headers, b"".join(chunks))
        return result

    async def check_robots(self, url: str, *, within_slot: bool = False) -> None:
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        if origin not in self.robots:
            response = (
                await self._fetch(f"{origin}/robots.txt", follow_redirects=True)
                if within_slot
                else await self.fetch(f"{origin}/robots.txt")
            )
            parser = RobotFileParser()
            if response.status in {404, 410}:
                parser.parse([])
            elif response.status in {401, 403}:
                raise SourceNetworkError("robots_disallowed")
            else:
                response.require_success()
                parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
            self.robots[origin] = parser
        if not self.robots[origin].can_fetch("Extrio", url):
            raise SourceNetworkError("robots_disallowed")
