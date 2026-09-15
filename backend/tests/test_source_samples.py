import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from crawl4ai import CacheMode, CrawlerRunConfig
from test_runtime import runtime_spec

from extrio.config import Settings
from extrio.harvest import embedded_list_url
from extrio.runtime import CrawleeRuntime
from extrio.source_clients import RestrictedBrowser
from extrio.source_network import SourceNetwork, SourceNetworkError

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
CATALOG = json.loads((FIXTURES / "catalog.json").read_text())


@pytest.fixture
def source_server(monkeypatch):
    monkeypatch.setattr("extrio.runtime.get_settings", lambda: Settings(allow_http_localhost=True))
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            path = urlsplit(self.path).path
            status, location, encoding = 200, None, "utf-8"
            filename = {
                "/single": "single.html",
                "/list": "list.html",
                "/list-2": "list-2.html",
                "/json-list": "json-list.json",
                "/iframe": "iframe.html",
                "/async": "async.html",
                "/wrong": "wrong.html",
                "/robots.txt": "robots.txt",
            }.get(path)
            if path == "/paged":
                page = int(parse_qs(urlsplit(self.path).query).get("page", ["1"])[0])
                filename = "list.html" if page == 1 else "list-2.html" if page == 2 else None
            elif path == "/charset":
                filename, encoding = "single.html", "gb18030"
            elif path == "/redirect":
                status, location = 302, "/single"
            elif path == "/redirect-relative":
                status, location = 302, "/nested/single"
            elif path.startswith("/redirect-chain/"):
                index = int(path.rsplit("/", 1)[1])
                status, location = 302, f"/redirect-chain/{index + 1}" if index < 2 else "/single"
            elif path == "/redirect-list":
                status, location = 302, "/nested/list"
            elif path == "/nested/list":
                filename = "list.html"
            elif path == "/nested/single":
                filename = "single.html"
            elif path == "/redirect-blocked":
                status, location = 302, "http://localhost/forbidden"
            elif path == "/forbidden":
                status = 403
            elif path == "/transient":
                status = 503 if hits.count("/transient") == 1 else 200
                filename = "single.html"
            body = (FIXTURES / filename).read_text() if filename else "<html><body></body></html>"
            if path == "/nested/list":
                body = body.replace('href="/single"', 'href="single"')
            if path == "/nested/single":
                body += '<a class="reference" href="attachment.pdf">Reference</a>'
            if path == "/charset":
                body = body.replace("utf-8", encoding).replace(">A<", ">采购公告<")
            if path == "/subrequest-blocked":
                body = '<html><script>fetch("http://localhost/not-allowed")</script></html>'
            if path == "/auxiliary-blocked":
                body = (FIXTURES / "list.html").read_text() + (
                    '<script src="http://localhost/not-allowed.js"></script>'
                    '<img src="http://localhost/not-allowed.png">'
                )
            if path == "/frame-blocked":
                body = '<html><iframe src="http://localhost/not-allowed-frame"></iframe></html>'
            if path == "/timeout-once":
                body = (FIXTURES / "list.html").read_text() + '<script src="/slow-script.js"></script>'
            if path == "/slow-script.js":
                body = ""
            payload = body.encode(encoding)
            self.send_response(status)
            self.send_header("Content-Type", f"{'application/json' if filename == 'json-list.json' else 'text/html'}; charset={encoding}")
            self.send_header("Content-Length", str(len(payload)))
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", hits
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


async def progress(*_args):
    pass


async def test_relative_links_use_the_redirected_list_url(source_server, tmp_path):
    origin, hits = source_server
    url = origin + "/redirect-list"
    spec = runtime_spec(url, mode="list_detail")
    spec["collect"]["list"]["pagination"] = {"type": "none"}
    collector = {
        "id": "collector_redirect",
        "name": "Redirect",
        "collectionVersion": "v1",
        "sourceUrl": url,
        "sourceHost": "127.0.0.1",
        "candidate": {"gatherSpec": spec},
    }
    result = await CrawleeRuntime(tmp_path).run(collector, {"id": "run_redirect", "ruleVersion": "rule_1"}, progress)
    assert result.items
    assert "/nested/single" in hits


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", CATALOG, ids=lambda sample: sample["id"])
async def test_repeatable_source_catalog(sample, source_server, tmp_path):
    origin, _hits = source_server
    url = origin + sample["path"]
    if sample["id"] == "iframe-shell":
        network = SourceNetwork({"127.0.0.1"}, allow_localhost=True)
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False, delay_before_return_html=0.2)
        async with RestrictedBrowser(network) as browser:
            shell = await browser.arun(url, config)
            frame = embedded_list_url(shell.html, url)
            assert frame == origin + "/list"
            result = await browser.arun(frame, config)
        assert "notice-list" in result.html
        return
    mode = "list_detail" if sample["id"] in {"list-next", "list-page", "json-list-detail", "wrong-page"} else "single"
    spec = runtime_spec(url, mode=mode)
    if sample["id"] == "list-page":
        spec["collect"]["list"]["pagination"] = {"type": "page", "parameter": "page", "start": 1, "step": 1, "maxPages": 2}
    if sample["id"] == "async-dom":
        spec["sourceContext"].update(transport="browser", browserPolicy={"postLoadDelayMs": 250})
    if sample["id"] == "json-list-detail":
        fields = spec["collect"]["list"]["fields"]
        fields["listTitle"]["selector"] = "jsonpath:$.title"
        fields["listPublishedAt"]["selector"] = "jsonpath:$.date"
        fields["detailUrl"]["selector"] = "jsonpath:$.url"
        spec["collect"]["list"].update(itemsSelector="jsonpath:$.items[*]", pagination={"type": "none"})
    collector = {
        "id": "collector_sample",
        "name": "Sample",
        "sourceUrl": url,
        "sourceHost": "127.0.0.1",
        "candidate": {"gatherSpec": spec},
        "collectionVersion": "v1",
    }
    runtime = CrawleeRuntime(tmp_path)
    if sample["expect"] in {"host_not_allowed", "robots_disallowed", "authentication_or_access_required", "source_structure_mismatch"}:
        with pytest.raises(SourceNetworkError, match=sample["expect"]):
            await runtime.run(collector, {"id": "run_sample", "ruleVersion": "rule_1"}, progress)
        return
    result = await runtime.run(collector, {"id": "run_sample", "ruleVersion": "rule_1"}, progress)
    assert len(result.items) == (2 if sample["expect"] == "two-items" else 1)
    assert all(item["decision"] == "accepted" for item in result.items)
    if sample["expect"] == "decoded-item":
        assert result.items[0]["title"] == "采购公告"


@pytest.mark.asyncio
async def test_browser_blocks_cross_host_xhr(source_server):
    origin, hits = source_server
    network = SourceNetwork({"127.0.0.1"}, allow_localhost=True)
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False, delay_before_return_html=0.2)
    async with RestrictedBrowser(network) as browser:
        with pytest.raises(SourceNetworkError, match="host_not_allowed"):
            await browser.arun(origin + "/subrequest-blocked", config)
    assert not any("not-allowed" in path for path in hits)


@pytest.mark.asyncio
async def test_blocked_auxiliary_assets_do_not_discard_valid_page(source_server):
    origin, hits = source_server
    network = SourceNetwork({"127.0.0.1"}, allow_localhost=True)
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False, delay_before_return_html=0.2)
    async with RestrictedBrowser(network) as browser:
        result = await browser.arun(origin + "/auxiliary-blocked", config)
        assert "notice-list" in result.html
    assert not any("not-allowed" in path for path in hits)


@pytest.mark.asyncio
async def test_browser_still_rejects_cross_host_frame(source_server):
    origin, hits = source_server
    network = SourceNetwork({"127.0.0.1"}, allow_localhost=True)
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False, delay_before_return_html=0.2)
    async with RestrictedBrowser(network) as browser:
        with pytest.raises(SourceNetworkError, match="host_not_allowed"):
            await browser.arun(origin + "/frame-blocked", config)
    assert not any("not-allowed" in path for path in hits)


@pytest.mark.asyncio
async def test_browser_recovers_from_one_navigation_timeout(source_server):
    origin, hits = source_server
    network = SourceNetwork({"127.0.0.1"}, allow_localhost=True)
    fetch = network.fetch
    delayed = False

    async def delayed_fetch(url, **kwargs):
        nonlocal delayed
        if url.endswith("/slow-script.js") and not delayed:
            delayed = True
            await asyncio.sleep(4)
        return await fetch(url, **kwargs)

    network.fetch = delayed_fetch
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False,
                              page_timeout=2000, delay_before_return_html=0.1)
    async with RestrictedBrowser(network) as browser:
        result = await browser.arun(origin + "/timeout-once", config)
    assert delayed
    assert result.status_code == 200
    assert hits.count("/timeout-once") == 2
    assert "notice-list" in result.html


@pytest.mark.asyncio
async def test_browser_respects_declared_redirect_chain_limit(source_server):
    origin, hits = source_server
    network = SourceNetwork({"127.0.0.1"}, allow_localhost=True, max_redirects=1)
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, check_robots_txt=False, delay_before_return_html=0)
    async with RestrictedBrowser(network) as browser:
        with pytest.raises(SourceNetworkError, match="redirect_limit_exceeded"):
            await browser.arun(origin + "/redirect-chain/0", config)
    assert "/redirect-chain/2" not in hits


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "browser"])
async def test_redirect_uses_final_url_for_extracted_relative_fields(transport, source_server, tmp_path):
    origin, _ = source_server
    spec = runtime_spec(origin + "/redirect-relative", mode="single")
    spec["sourceContext"]["transport"] = transport
    spec["sourceContext"]["browserPolicy"] = {"postLoadDelayMs": 0}
    spec["collect"]["list"]["fields"]["referenceUrl"] = {
        "selector": "css:a.reference::attr(href)",
        "valueType": "url",
        "transforms": ["absolute_url"],
    }
    collector = {
        "id": "collector_sample",
        "name": "Sample",
        "sourceUrl": origin + "/redirect-relative",
        "sourceHost": "127.0.0.1",
        "candidate": {"gatherSpec": spec},
        "collectionVersion": "v1",
    }
    result = await CrawleeRuntime(tmp_path).run(collector, {"id": "run_sample", "ruleVersion": "rule_1"}, progress)
    assert result.items[0]["decision"] == "accepted"
    assert result.items[0]["sourceUrl"] == origin + "/nested/single"
    assert result.items[0]["extractedData"]["referenceUrl"] == origin + "/nested/attachment.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["access_profile", "authorization", "post"])
async def test_unsupported_auth_or_method_is_rejected_before_network(change, source_server, tmp_path):
    origin, hits = source_server
    spec = runtime_spec(origin + "/single", mode="single")
    if change == "access_profile":
        spec["sourceContext"]["accessProfileRef"] = {"accessProfileId": "profile_old", "accessProfileVersionId": "profile_version_expired"}
    elif change == "authorization":
        spec["collect"]["list"]["request"] = {"headers": {"Authorization": "Bearer should-not-leak"}}
    else:
        spec["collect"]["list"]["request"] = {"method": "POST"}
    collector = {
        "id": "collector_sample",
        "name": "Sample",
        "sourceUrl": origin + "/single",
        "sourceHost": "127.0.0.1",
        "candidate": {"gatherSpec": spec},
        "collectionVersion": "v1",
    }
    with pytest.raises(SourceNetworkError, match="anonymous_get_only"):
        await CrawleeRuntime(tmp_path).run(collector, {"id": "run_sample", "ruleVersion": "rule_1"}, progress)
    assert hits == []


@pytest.mark.asyncio
async def test_transient_http_failure_can_recover_within_retry_budget(source_server, tmp_path):
    origin, hits = source_server
    spec = runtime_spec(origin + "/transient", mode="single")
    collector = {
        "id": "collector_sample",
        "name": "Sample",
        "sourceUrl": origin + "/transient",
        "sourceHost": "127.0.0.1",
        "candidate": {"gatherSpec": spec},
        "collectionVersion": "v1",
    }
    result = await CrawleeRuntime(tmp_path).run(collector, {"id": "run_sample", "ruleVersion": "rule_1"}, progress)
    assert result.items[0]["decision"] == "accepted"
    assert hits.count("/transient") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,policy,reason",
    [
        ("/redirect", {"maxRedirects": 0}, "redirect_limit_exceeded"),
        ("/single", {"maxResponseBytes": 16}, "page_bytes_exceeded"),
        ("/transient", {"attempts": 1}, "http_status_503"),
        ("/forbidden", {}, "authentication_or_access_required"),
    ],
)
async def test_frozen_request_limits_and_permanent_failures(path, policy, reason, source_server, tmp_path):
    origin, hits = source_server
    spec = runtime_spec(origin + path, mode="single")
    spec["sourceContext"].setdefault("requestPolicy", {}).update({key: value for key, value in policy.items() if key != "attempts"})
    if "attempts" in policy:
        spec["collect"]["requestRetry"] = {"maxAttempts": policy["attempts"]}
    collector = {
        "id": "collector_sample",
        "name": "Sample",
        "sourceUrl": origin + path,
        "sourceHost": "127.0.0.1",
        "candidate": {"gatherSpec": spec},
        "collectionVersion": "v1",
    }
    with pytest.raises(SourceNetworkError, match=reason):
        await CrawleeRuntime(tmp_path).run(collector, {"id": "run_sample", "ruleVersion": "rule_1"}, progress)
    assert hits.count(path) <= 1
