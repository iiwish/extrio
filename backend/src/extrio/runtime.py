from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import UnicodeDammit
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawlee import Request
from crawlee.crawlers import ParselCrawler, ParselCrawlingContext
from crawlee.storage_clients import MemoryStorageClient

from extrio.harvest import discover_records_from_spec, looks_like_dynamic_list_shell, make_item

ProgressCallback = Callable[[str, int, dict[str, int]], Awaitable[None]]


@dataclass
class RunResult:
    items: list[dict[str, Any]]
    metrics: dict[str, int]
    pagination_stop_reason: str
    duration: str
    watermark_candidate: str | None = None


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


class CrawleeRuntime:
    def __init__(self, artifact_path: Path):
        self.artifact_path = artifact_path

    async def _fetch_many(
        self,
        urls: list[str],
        transport: str = "http",
        browser_policy: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        if transport == "browser":
            pages: dict[str, str] = {}
            policy = browser_policy or {}
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                check_robots_txt=True,
                page_timeout=int(policy.get("pageLoadTimeoutMs", 30_000)),
                wait_until=str(policy.get("waitUntil", "domcontentloaded")),
                delay_before_return_html=max(0, int(policy.get("postLoadDelayMs", 3000))) / 1000,
            )
            async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
                results = await crawler.arun_many(urls=urls, config=config)
                for requested_url, result in zip(urls, results, strict=False):
                    if result.success:
                        html = result.html
                        if looks_like_dynamic_list_shell(html):
                            settled_result = await crawler.arun(url=requested_url, config=config)
                            if settled_result.success:
                                html = settled_result.html
                        pages[requested_url] = html
            return pages
        pages: dict[str, str] = {}
        crawler = ParselCrawler(
            max_requests_per_crawl=max(1, len(urls)),
            max_request_retries=2,
            storage_client=MemoryStorageClient(),
        )

        @crawler.router.default_handler
        async def handler(context: ParselCrawlingContext) -> None:
            # Preserve the response source. Serializing Parsel's lxml tree can
            # rewrite invalid-but-common publisher markup, so selectors proven
            # against onboarding evidence would otherwise execute against a
            # different DOM shape at runtime.
            body = await context.http_response.read()
            pages[context.request.url] = UnicodeDammit(body).unicode_markup or body.decode("utf-8", errors="replace")

        requests = [Request.from_url(url, always_enqueue=True) for url in urls]
        await crawler.run(requests)
        return pages

    @staticmethod
    def _page_url(entrypoint: str, pagination: dict[str, Any], page_index: int) -> str:
        parts = urlsplit(entrypoint)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query[str(pagination["parameter"])] = str(int(pagination["start"]) + page_index * int(pagination["step"]))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    async def run(self, collector: dict[str, Any], run: dict[str, Any], progress: ProgressCallback) -> RunResult:
        started = monotonic()
        artifact_dir = self.artifact_path / run["id"]
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
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
        gather_spec = collector["candidate"]["gatherSpec"]
        collect = gather_spec["collect"]
        list_spec = collect["list"]
        mode = "list_detail" if "detail" in collect else "single"
        entrypoint = gather_spec["sourceContext"]["entrypoints"][0]
        transport = gather_spec["sourceContext"].get("transport", "http")
        browser_policy = gather_spec["sourceContext"].get("browserPolicy")
        watermark_candidate: str | None = None

        if mode == "single":
            await progress("fetching_details", 35, metrics)
            pages = await self._fetch_many([entrypoint], transport, browser_policy)
            detail_pages = [(url, html, None) for url, html in pages.items()]
            metrics["detailPagesFetched"] = len(detail_pages)
            stop_reason = "not_applicable"
        else:
            await progress("fetching_list", 15, metrics)
            next_url: str | None = entrypoint
            detail_records: dict[str, dict[str, str]] = {}
            seen_pages: set[str] = set()
            allowed_hosts = {str(host).lower() for host in gather_spec["sourceContext"]["allowedHosts"]}
            pagination = list_spec["pagination"]
            policy = collector.get("collectionPolicy") or {}
            max_pages = min(
                int(pagination.get("maxPages", 1)),
                int(collect["budget"]["maxPages"]),
                int(policy.get("maxPages", 1_000)),
                1_000,
            )
            max_items = min(int(collect["budget"]["maxItems"]), int(policy.get("maxItems", 100_000)), 100_000)
            window_start = _as_date(run.get("windowStart"))
            consecutive_older_pages = 0
            required_older_pages = int(policy.get("consecutiveOlderPages", 2))
            list_published_binding = gather_spec.get("contract", {}).get("fieldBindings", {}).get("listPublishedAt", "list.listPublishedAt")
            list_published_key = list_published_binding.split(".", 1)[1] if list_published_binding.startswith("list.") else ""
            window_enabled = bool(policy and window_start and list_published_key in list_spec.get("fields", {}))
            stop_reason = "max_pages"
            for page_index in range(max_pages):
                if not next_url or next_url in seen_pages:
                    stop_reason = "next_link_exhausted"
                    break
                if (urlsplit(next_url).hostname or "").lower() not in allowed_hosts:
                    stop_reason = "cross_host_blocked"
                    break
                seen_pages.add(next_url)
                fetched = await self._fetch_many([next_url], transport, browser_policy)
                html = fetched.get(next_url)
                if html is None:
                    stop_reason = "empty_page"
                    break
                metrics["listPagesFetched"] += 1
                (artifact_dir / f"list-{page_index + 1:03d}.html").write_text(html, encoding="utf-8")
                discovered, discovered_next_url = discover_records_from_spec(html, next_url, list_spec)
                if pagination.get("type") == "page":
                    if not discovered and pagination.get("stopWhenNoItems", True):
                        next_url = None
                        stop_reason = "next_link_exhausted"
                    else:
                        next_url = self._page_url(entrypoint, pagination, page_index + 1)
                else:
                    next_url = discovered_next_url
                page_is_strictly_older = bool(discovered) and window_enabled
                for record in discovered:
                    published_date = _as_date(record.get(list_published_key))
                    if window_enabled and published_date is None:
                        page_is_strictly_older = False
                    elif window_enabled and published_date and published_date < window_start:
                        metrics["recordsOutsideWindow"] += 1
                        continue
                    else:
                        page_is_strictly_older = False
                    if published_date and (watermark_candidate is None or published_date > _as_date(watermark_candidate)):
                        watermark_candidate = published_date.isoformat()
                    url = record["detailUrl"]
                    if (urlsplit(url).hostname or "").lower() in allowed_hosts:
                        if url in detail_records:
                            metrics["duplicateDetailUrls"] += 1
                        else:
                            detail_records[url] = record
                    if len(detail_records) >= max_items:
                        stop_reason = "max_items"
                        break
                if stop_reason == "max_items":
                    break
                consecutive_older_pages = consecutive_older_pages + 1 if page_is_strictly_older else 0
                if consecutive_older_pages >= required_older_pages:
                    stop_reason = "checkpoint_reached" if run.get("executionMode") == "incremental" else "time_window_reached"
                    break
                if not next_url:
                    stop_reason = "next_link_exhausted"
                    break
            detail_records = dict(list(detail_records.items())[:max_items])
            detail_urls = list(detail_records)
            metrics["detailUrlsDiscovered"] = len(detail_urls)
            await progress("discovering_details", 45, metrics)
            pages = await self._fetch_many(detail_urls, transport, browser_policy)
            detail_pages = [(url, pages[url], detail_records[url]) for url in detail_urls if url in pages]
            metrics["detailPagesFetched"] = len(detail_pages)
            missing_detail_pages = len(detail_urls) - len(detail_pages)
            if missing_detail_pages:
                metrics["warningCount"] += missing_detail_pages
                stop_reason = "detail_fetch_incomplete"
            await progress("fetching_details", 75, metrics)

        items = []
        for index, (url, html, source_record) in enumerate(detail_pages, start=1):
            (artifact_dir / f"detail-{index:03d}.html").write_text(html, encoding="utf-8")
            items.append(make_item(collector, run, url, html, index, source_record=source_record))
        await progress("validating", 90, metrics)
        elapsed = max(0.01, monotonic() - started)
        return RunResult(
            items=items,
            metrics=metrics,
            pagination_stop_reason=stop_reason,
            duration=f"{elapsed:.1f}s",
            watermark_candidate=watermark_candidate,
        )
