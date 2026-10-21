import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from crawlee import HttpHeaders
from crawlee.http_clients import HttpClient, HttpCrawlingResult
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from extrio.source_network import SourceNetwork, SourceNetworkError, SourceResponse

logger = logging.getLogger(__name__)


class CrawleeResponse:
    def __init__(self, response: SourceResponse):
        self.response = response
        self.http_version = "HTTP/1.1"
        self.status_code = response.status
        self.headers = HttpHeaders(response.headers)

    async def read(self) -> bytes:
        return self.response.body

    async def read_stream(self):
        yield self.response.body


class SourceHttpClient(HttpClient):
    def __init__(self, network: SourceNetwork):
        super().__init__(persist_cookies_per_session=False)
        self.network = network
        self.failures: dict[str, SourceNetworkError] = {}

    async def crawl(self, request, *, statistics=None, **_kwargs):
        try:
            await self.network.check_robots(request.url)
            response = (await self.network.fetch(request.url, respect_robots=True)).require_success()
        except SourceNetworkError as exc:
            self.failures[request.url] = exc
            request.no_retry = str(exc) not in {
                "source_connection_failed",
                "source_request_timed_out",
                "http_status_408",
                "http_status_429",
                "http_status_500",
                "http_status_502",
                "http_status_503",
                "http_status_504",
            }
            raise
        self.failures.pop(request.url, None)
        request.loaded_url = response.url
        if statistics:
            statistics.register_status_code(response.status)
        return HttpCrawlingResult(http_response=CrawleeResponse(response))

    async def send_request(self, url, *, method="GET", headers=None, payload=None, **_kwargs):
        if method != "GET" or headers or payload:
            raise SourceNetworkError("anonymous_get_only")
        return CrawleeResponse((await self.network.fetch(url)).require_success())

    @asynccontextmanager
    async def stream(self, url, **kwargs):
        yield await self.send_request(url, **kwargs)

    async def cleanup(self):
        pass


@dataclass(frozen=True)
class BrowserSnapshotConfig:
    page_timeout: int = 30_000
    wait_until: str = 'domcontentloaded'
    delay_before_return_html: float = 3.0


@dataclass(frozen=True)
class BrowserSnapshot:
    html: str
    redirected_url: str
    status_code: int


class RestrictedBrowser:
    """Render with Playwright; all source requests use the pinned HTTP guard."""

    def __init__(self, network: SourceNetwork):
        self.network = network
        self.failures: list[SourceNetworkError] = []
        self.playwright = None
        self.browser = None
        self.server = None
        self.contexts: set[Any] = set()
        self.prefetched: dict[str, SourceResponse] = {}

    async def __aenter__(self):
        async def deny_connection(_reader, writer):
            writer.close()
            await writer.wait_closed()

        # The proxy never forwards. Requests missed by interception (including
        # service-worker traffic) cannot bypass the guard via Chromium's stack.
        self.server = await asyncio.start_server(deny_connection, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True, proxy={"server": f"http://127.0.0.1:{port}"},
                args=[
                    "--proxy-bypass-list=<-loopback>",
                    "--disable-quic",
                    "--disable-background-networking",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ],
            )
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            try:
                if self.playwright:
                    await self.playwright.stop()
            finally:
                if self.server:
                    self.server.close()
                    await self.server.wait_closed()

    async def _snapshot(self, url: str, config: BrowserSnapshotConfig) -> BrowserSnapshot:
        context = await self.browser.new_context(
            service_workers='block', accept_downloads=False, ignore_https_errors=False,
            viewport={'width': 1080, 'height': 600}, device_scale_factor=1,
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36',
        )
        try:
            page = await context.new_page()
            await self.install_routes(page, context)
            response = await page.goto(url, wait_until=config.wait_until, timeout=config.page_timeout)
            await asyncio.sleep(config.delay_before_return_html)
            return BrowserSnapshot(await page.content(), page.url, response.status if response else 0)
        finally:
            await context.close()
            self.contexts.discard(context)

    async def install_routes(self, page, context, **_kwargs):
        if context in self.contexts:
            return page
        self.contexts.add(context)

        async def route_request(route):
            request = route.request
            page = request.frame.page
            try:
                if request.method != "GET":
                    raise SourceNetworkError("anonymous_get_only")
                if not request.is_navigation_request() and request.resource_type in {"image", "font", "media"}:
                    await route.abort("blockedbyclient")
                    return
                if request.is_navigation_request():
                    await self.network.check_robots(request.url)
                response = self.prefetched.pop(request.url, None)
                if response is None:
                    response = await self.network.fetch(request.url, respect_robots=request.is_navigation_request())
                if response.url != request.url:
                    raise SourceNetworkError("browser_subresource_redirect_unsupported")
                headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in {"content-length", "transfer-encoding", "connection", "set-cookie", "content-encoding"}
                }
                await route.fulfill(status=response.status, headers=headers, body=response.body)
            except SourceNetworkError as exc:
                if page.is_closed():
                    return
                # Denied ancillary assets must not invalidate an otherwise valid
                # snapshot. Documents and data requests still fail closed.
                auxiliary = (
                    str(exc) == "host_not_allowed"
                    and not request.is_navigation_request()
                    and request.resource_type in {"script", "stylesheet", "image", "font", "media"}
                )
                if auxiliary:
                    logger.warning(
                        "Blocked out-of-scope browser asset type=%s host=%s",
                        request.resource_type, urlsplit(request.url).hostname,
                    )
                else:
                    self.failures.append(exc)
                try:
                    await route.abort("blockedbyclient")
                except PlaywrightError:
                    if not page.is_closed():
                        raise
            except PlaywrightError:
                if not page.is_closed():
                    raise

        async def block_socket(socket):
            self.failures.append(SourceNetworkError("websocket_unsupported"))
            await socket.close()

        await context.route("**/*", route_request)
        await context.route_web_socket("**/*", block_socket)
        return page

    async def arun(self, url, config):
        for attempt in range(2):
            try:
                return await self._arun_once(url, config)
            except SourceNetworkError as exc:
                if str(exc) != "browser_navigation_timed_out" or attempt:
                    raise
                logger.warning("Browser navigation timed out; retrying once within the source budget")

    async def _arun_once(self, url, config):
        await self.network.check_robots(url)
        self.failures.clear()
        initial = (await self.network.fetch(url, respect_robots=True)).require_success()
        await self.network.check_robots(initial.url)
        self.prefetched = {initial.url: initial}
        try:
            result = await self._snapshot(initial.url, config)
        except PlaywrightError as exc:
            if self.failures:
                raise self.failures[0] from exc
            reason = 'browser_navigation_timed_out' if isinstance(exc, PlaywrightTimeoutError) else 'browser_fetch_failed'
            raise SourceNetworkError(reason) from exc
        if self.failures:
            raise self.failures[0]
        status = result.status_code
        if status:
            SourceResponse(url, status, {}, b"").require_success()
        if not status:
            raise SourceNetworkError("browser_fetch_failed")
        await self.network.target(result.redirected_url or initial.url)
        self.network.final_urls[url] = result.redirected_url or initial.url
        return result
