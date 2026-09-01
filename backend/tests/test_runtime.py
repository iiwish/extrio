import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from extrio.runtime import CrawleeRuntime


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/window-list"):
            page = int(parse_qs(urlsplit(self.path).query).get("page", ["1"])[0])
            rows = {
                1: [("new-a", "2026-08-30"), ("new-b", "2026-08-29")],
                2: [("old-a", "2026-07-02"), ("old-b", "2026-07-01")],
                3: [("old-c", "2026-06-30"), ("old-d", "2026-06-29")],
            }[page]
            items = "".join(
                f'<li><a class="notice-title" href="/window-detail/{code}">{code}</a><time datetime="{published}">{published}</time></li>'
                for code, published in rows
            )
            next_link = f'<a class="pagination-next" href="/window-list?page={page + 1}">Next</a>' if page < 3 else ""
            body = f'<ul class="notice-list">{items}</ul>{next_link}'
        elif self.path.startswith("/window-detail/"):
            code = self.path.rsplit("/", 1)[-1]
            published = {"new-a": "2026-08-30", "new-b": "2026-08-29"}.get(code, "2026-07-01")
            body = (
                f'<h1 class="notice-title">{code}</h1><div class="meta"><span data-field="buyer">B</span>'
                f'<time datetime="{published}"></time></div><div class="notice-budget"><span class="amount">100</span></div>'
            )
        elif self.path.startswith("/cross-list"):
            port = self.server.server_address[1]
            body = (
                '<ul class="notice-list"><li><a class="notice-title" href="/detail">A</a></li></ul>'
                f'<a class="pagination-next" href="http://localhost:{port}/cross-list?page=2">Next</a>'
            )
        elif self.path.startswith("/spec-list"):
            body = '<main><article class="entry"><a class="go" href="/spec-detail">A</a></article></main>'
        elif self.path.startswith("/page-list"):
            page = int(parse_qs(urlsplit(self.path).query).get("p", ["1"])[0])
            body = (
                f'<main><article class="entry"><a class="go" href="/page-detail/{page}">A{page}</a></article></main>'
                if page <= 2
                else "<main></main>"
            )
        elif self.path.startswith("/page-detail/"):
            page = self.path.rsplit("/", 1)[-1]
            body = (
                f'<h2 class="headline">Page {page}</h2><div class="purchaser">Buyer {page}</div>'
                '<time class="pubdate" datetime="2026-08-30T00:00:00Z"></time><span class="value">200</span>'
            )
        elif self.path.startswith("/spec-detail"):
            body = (
                '<h2 class="headline">Spec A</h2><div class="purchaser">Spec B</div>'
                '<time class="pubdate" datetime="2026-08-30T00:00:00Z"></time><span class="value">200</span>'
            )
        elif self.path.startswith("/list"):
            body = (
                '<ul class="notice-list"><li><a class="notice-title" href="/detail">A</a>'
                '<time datetime="2026-08-30T00:00:00Z"></time></li></ul>'
            )
        elif self.path.startswith("/shell"):
            body = '<iframe src="/detail"></iframe>'
        else:
            body = (
                '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">B</span>'
                '<span data-field="region">北京</span><time datetime="2026-08-30T00:00:00Z"></time></div>'
                '<p class="notice-budget"><span class="amount">100</span></p>'
            )
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *args: object) -> None:
        return


@contextmanager
def fixture_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def runtime_spec(entrypoint: str, *, mode: str) -> dict:
    fields = {
        "title": {
            "selector": "css:h1.notice-title::text",
            "required": True,
            "multipleMatchPolicy": "error",
            "transforms": ["trim", "collapse_whitespace"],
        },
        "buyer": {
            "selector": 'css:.meta [data-field="buyer"]::text',
            "required": True,
            "multipleMatchPolicy": "error",
            "transforms": ["trim"],
        },
        "publishedAt": {
            "selector": "css:time[datetime]::attr(datetime)",
            "required": True,
            "multipleMatchPolicy": "error",
            "transforms": ["trim"],
        },
        "budget": {
            "selector": "css:.notice-budget .amount::text",
            "required": False,
            "multipleMatchPolicy": "first",
            "transforms": ["trim"],
        },
    }
    collect = {
        "list": {
            "itemsSelector": "css:.notice-list > li" if mode == "list_detail" else "css:body",
            "fields": (
                {
                    "listTitle": {
                        "selector": "css:a.notice-title::text",
                        "required": True,
                        "multipleMatchPolicy": "error",
                        "transforms": ["trim", "collapse_whitespace"],
                    },
                    "listPublishedAt": {
                        "selector": "css:time::attr(datetime)",
                        "required": True,
                        "multipleMatchPolicy": "error",
                        "transforms": ["trim"],
                    },
                    "detailUrl": {
                        "selector": "css:a.notice-title::attr(href)",
                        "required": True,
                        "multipleMatchPolicy": "error",
                        "transforms": ["trim", "absolute_url"],
                    }
                }
                if mode == "list_detail"
                else fields
            ),
            "pagination": (
                {"type": "next_link", "selector": "css:a.pagination-next", "maxPages": 2, "allowCrossHost": False}
                if mode == "list_detail"
                else {"type": "none"}
            ),
        },
        "budget": {"maxPages": 2, "maxItems": 100},
    }
    if mode == "list_detail":
        collect["detail"] = {"fields": fields}
    return {
        "sourceContext": {"entrypoints": [entrypoint], "allowedHosts": ["127.0.0.1"]},
        "collect": collect,
        "sourceRevisionRef": {"sourceRevisionId": "source_revision_1"},
    }


@pytest.mark.asyncio
async def test_initial_window_stops_after_two_old_pages_and_skips_old_details(tmp_path: Path) -> None:
    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    with fixture_server() as origin:
        spec = runtime_spec(f"{origin}/window-list?page=1", mode="list_detail")
        spec["collect"]["list"]["pagination"]["maxPages"] = 10
        spec["collect"]["budget"]["maxPages"] = 10
        collector = {
            "id": "collector_window",
            "name": "Window",
            "sourceUrl": f"{origin}/window-list?page=1",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "v1",
            "collectionPolicy": {
                "id": "policy_window_v1",
                "initialWindowDays": 30,
                "lookbackDays": 3,
                "consecutiveOlderPages": 2,
                "maxPages": 10,
                "maxItems": 100,
                "timezone": "Asia/Shanghai",
            },
            "candidate": {"mode": "list_detail", "gatherSpec": spec},
        }
        result = await CrawleeRuntime(tmp_path / "artifacts").run(
            collector,
            {
                "id": "run_window",
                "ruleVersion": "rule_v1",
                "executionMode": "initial",
                "windowStart": "2026-08-01",
                "checkpointBefore": None,
            },
            progress,
        )

    assert result.pagination_stop_reason == "time_window_reached"
    assert result.metrics["listPagesFetched"] == 3
    assert result.metrics["recordsOutsideWindow"] == 4
    assert result.metrics["detailPagesFetched"] == 2
    assert [item["title"] for item in result.items] == ["new-a", "new-b"]
    assert result.watermark_candidate == "2026-08-30"


@pytest.mark.asyncio
async def test_repeated_runs_do_not_reuse_crawlee_request_queue(tmp_path: Path) -> None:
    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    with fixture_server() as origin:
        collector = {
            "id": "collector_repeat",
            "name": "Repeat",
            "sourceUrl": f"{origin}/list",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "v1",
            "candidate": {
                "mode": "list_detail",
                "pagination": {"type": "next_link", "maxPages": 2},
                "gatherSpec": runtime_spec(f"{origin}/list", mode="list_detail"),
            },
        }
        runtime = CrawleeRuntime(tmp_path / "artifacts")
        first = await runtime.run(collector, {"id": "run_first", "ruleVersion": "rule_v1"}, progress)
        second = await runtime.run(collector, {"id": "run_second", "ruleVersion": "rule_v1"}, progress)
    assert [item["decision"] for item in first.items] == ["accepted"]
    assert [item["decision"] for item in second.items] == ["accepted"]


@pytest.mark.asyncio
async def test_single_stage_fetches_entrypoint_directly(tmp_path: Path) -> None:
    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    with fixture_server() as origin:
        collector = {
            "id": "collector_single",
            "name": "Single",
            "sourceUrl": f"{origin}/shell",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "v1",
            "candidate": {
                "mode": "single",
                "pagination": {"type": "none"},
                "gatherSpec": runtime_spec(f"{origin}/detail", mode="single"),
            },
        }
        result = await CrawleeRuntime(tmp_path / "artifacts").run(
            collector,
            {"id": "run_single", "ruleVersion": "rule_v1"},
            progress,
        )
    assert [item["decision"] for item in result.items] == ["accepted"]
    assert result.metrics["listPagesFetched"] == 0
    assert result.metrics["detailPagesFetched"] == 1
    assert result.pagination_stop_reason == "not_applicable"


@pytest.mark.asyncio
async def test_runtime_executes_published_gather_spec_selectors(tmp_path: Path) -> None:
    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    with fixture_server() as origin:
        spec = runtime_spec(f"{origin}/spec-list", mode="list_detail")
        spec["collect"]["list"]["itemsSelector"] = "css:article.entry"
        spec["collect"]["list"]["fields"]["detailUrl"]["selector"] = "css:a.go::attr(href)"
        fields = spec["collect"]["detail"]["fields"]
        fields["title"]["selector"] = "css:h2.headline::text"
        fields["buyer"]["selector"] = "css:.purchaser::text"
        fields["publishedAt"]["selector"] = "css:time.pubdate::attr(datetime)"
        fields["budget"]["selector"] = "css:.value::text"
        collector = {
            "id": "collector_spec",
            "name": "Spec",
            "sourceUrl": f"{origin}/spec-list",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "v1",
            "candidate": {"mode": "list_detail", "gatherSpec": spec},
        }
        result = await CrawleeRuntime(tmp_path / "artifacts").run(
            collector,
            {"id": "run_spec", "ruleVersion": "rule_v1"},
            progress,
        )
    assert result.items[0]["title"] == "Spec A"
    assert result.items[0]["buyer"] == "Spec B"
    assert result.items[0]["budget"] == "200"


@pytest.mark.asyncio
async def test_runtime_blocks_cross_host_pagination_from_published_spec(tmp_path: Path) -> None:
    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    with fixture_server() as origin:
        collector = {
            "id": "collector_cross_host",
            "name": "Cross host",
            "sourceUrl": f"{origin}/cross-list",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "v1",
            "candidate": {
                "mode": "list_detail",
                "gatherSpec": runtime_spec(f"{origin}/cross-list", mode="list_detail"),
            },
        }
        result = await CrawleeRuntime(tmp_path / "artifacts").run(
            collector,
            {"id": "run_cross_host", "ruleVersion": "rule_v1"},
            progress,
        )
    assert result.metrics["listPagesFetched"] == 1
    assert result.pagination_stop_reason == "cross_host_blocked"


@pytest.mark.asyncio
async def test_runtime_executes_page_query_pagination_from_published_spec(tmp_path: Path) -> None:
    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    with fixture_server() as origin:
        spec = runtime_spec(f"{origin}/page-list?p=1", mode="list_detail")
        spec["collect"]["list"]["itemsSelector"] = "css:article.entry"
        spec["collect"]["list"]["fields"]["detailUrl"]["selector"] = "css:a.go::attr(href)"
        spec["collect"]["list"]["pagination"] = {
            "type": "page",
            "parameter": "p",
            "location": "query",
            "start": 1,
            "step": 1,
            "maxPages": 5,
            "stopWhenNoItems": True,
        }
        spec["collect"]["budget"]["maxPages"] = 5
        fields = spec["collect"]["detail"]["fields"]
        fields["title"]["selector"] = "css:h2.headline::text"
        fields["buyer"]["selector"] = "css:.purchaser::text"
        fields["publishedAt"]["selector"] = "css:time.pubdate::attr(datetime)"
        fields["budget"]["selector"] = "css:.value::text"
        collector = {
            "id": "collector_page_query",
            "name": "Page query",
            "sourceUrl": f"{origin}/page-list?p=1",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "v1",
            "candidate": {"mode": "list_detail", "gatherSpec": spec},
        }
        result = await CrawleeRuntime(tmp_path / "artifacts").run(
            collector,
            {"id": "run_page_query", "ruleVersion": "rule_v1"},
            progress,
        )

    assert result.metrics["listPagesFetched"] == 3
    assert result.pagination_stop_reason == "next_link_exhausted"
    assert [item["title"] for item in result.items] == ["Page 1", "Page 2"]


@pytest.mark.asyncio
async def test_runtime_reports_missing_detail_pages_as_incomplete(tmp_path: Path) -> None:
    class PartialRuntime(CrawleeRuntime):
        async def _fetch_many(self, urls, transport="http", browser_policy=None):
            if urls == ["https://example.com/list"]:
                return {
                    urls[0]: (
                        '<ul class="notice-list">'
                        '<li><a class="notice-title" href="/detail/a">A</a><time datetime="2026-08-30"></time></li>'
                        '<li><a class="notice-title" href="/detail/b">B</a><time datetime="2026-08-30"></time></li>'
                        "</ul>"
                    )
                }
            return {
                "https://example.com/detail/a": (
                    '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">Buyer</span>'
                    '<time datetime="2026-08-30"></time></div><p class="notice-budget"><span class="amount">100</span></p>'
                )
            }

    async def progress(_phase: str, _value: int, _metrics: dict[str, int]) -> None:
        return

    spec = runtime_spec("https://example.com/list", mode="list_detail")
    spec["sourceContext"]["allowedHosts"] = ["example.com"]
    collector = {
        "id": "collector_partial",
        "name": "Partial",
        "sourceUrl": "https://example.com/list",
        "sourceHost": "example.com",
        "collectionVersion": "v1",
        "candidate": {"mode": "list_detail", "gatherSpec": spec},
    }

    result = await PartialRuntime(tmp_path / "artifacts").run(
        collector,
        {"id": "run_partial", "ruleVersion": "rule_v1"},
        progress,
    )

    assert result.pagination_stop_reason == "detail_fetch_incomplete"
    assert result.metrics["detailUrlsDiscovered"] == 2
    assert result.metrics["detailPagesFetched"] == 1
    assert result.metrics["warningCount"] == 1
    assert [item["title"] for item in result.items] == ["A"]
