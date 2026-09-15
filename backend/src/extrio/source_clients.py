import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from crawl4ai import AsyncWebCrawler, BrowserConfig
from crawlee import HttpHeaders
from crawlee.http_clients import HttpClient, HttpCrawlingResult
from playwright.async_api import Error as PlaywrightError

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


class RestrictedBrowser:
    """Render with Crawl4AI; all actual source requests use the pinned HTTP guard."""

    def __init__(self, network: SourceNetwork):
        self.network = network
        self.failures: list[SourceNetworkError] = []
        self.crawler = None
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
        self.crawler = AsyncWebCrawler(
            config=BrowserConfig(
                headless=True,
                verbose=False,
                ignore_https_errors=False,
                proxy_config={"server": f"http://127.0.0.1:{port}"},
                extra_args=[
                    "--proxy-bypass-list=<-loopback>",
                    "--disable-quic",
                    "--disable-background-networking",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ],
            )
        )
        self.crawler.crawler_strategy.set_hook("on_page_context_created", self.install_routes)
        try:
            await self.crawler.__aenter__()
        except BaseException:
            self.server.close()
            await self.server.wait_closed()
            raise
        return self

    async def __aexit__(self, *args):
        try:
            if self.crawler:
                await self.crawler.__aexit__(*args)
        finally:
            if self.server:
                self.server.close()
                await self.server.wait_closed()

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
        result = await self.crawler.arun(url=initial.url, config=config)
        if self.failures:
            raise self.failures[0]
        status = result.status_code
        if status:
            SourceResponse(url, status, {}, b"").require_success()
        # Crawl4AI labels short valid pages and iframe shells as structural
        # anti-bot failures. Keep their raw DOM for Extrio's selector validation;
        # genuine challenges and transport failures remain fatal.
        structural_only = (result.error_message or "").startswith("Blocked by anti-bot protection: Structural:")
        if not result.success and not structural_only:
            if "Page.goto: Timeout" in (result.error_message or ""):
                raise SourceNetworkError("browser_navigation_timed_out")
            raise SourceNetworkError("browser_fetch_failed")
        if not status:
            raise SourceNetworkError("browser_fetch_failed")
        await self.network.target(result.redirected_url or initial.url)
        self.network.final_urls[url] = result.redirected_url or initial.url
        return result
