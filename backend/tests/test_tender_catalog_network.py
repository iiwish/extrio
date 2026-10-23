"""Offline contracts for the opt-in catalog runner; never contact a real source."""

import asyncio
import json
import ssl
import stat
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.catalog import CatalogEntry  # noqa: E402
from tender_sources.catalog_run import CatalogRunner, RunLimits, _challenge  # noqa: E402


def entry(number=2, *, group="main", host="www.example.org", path="/notices"):
    return CatalogEntry(f"{group}-{number}", group, number, f"https://{host}{path}", "source", {})


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("extrio.source_network.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))])


def listing():
    return '<title>采购公告</title><ul><li><a href="/notice/1.html">测试设备采购项目招标公告</a><span>2026-10-20</span></li></ul>'


def detail():
    return (
        "<h1>测试设备采购项目招标公告</h1><span>发布时间：2026-10-20</span><article>"
        + "本项目采购设备公开招标，投标人应按要求提交投标材料。" * 30
        + "</article>"
    )


def transport_with(calls, *, reject=None):
    def handle(request):
        calls.append(str(request.url))
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if reject:
            return reject(request)
        return httpx.Response(
            200, text=detail() if path.startswith("/notice/") else listing(), headers={"content-type": "text/html; charset=utf-8"}
        )

    return httpx.MockTransport(handle)


def test_dry_run_preserves_all_rows_and_private_outputs(tmp_path):
    output = tmp_path / "private"
    runner = CatalogRunner([entry(), entry(3, group="review")], output)
    result = asyncio.run(runner.run(dry_run=True, limit=1))
    assert result["inputCount"] == 2
    assert result["requests"] == 0
    assert result["completedCount"] == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.rglob("*") if p.is_file())
    assert len((output / "matrix.csv").read_text().splitlines()) == 3


def test_review_does_not_request_details_and_robots_shared(tmp_path):
    calls = []
    runner = CatalogRunner(
        [entry(group="review"), entry(3, group="review")],
        tmp_path / "private",
        transport=transport_with(calls),
        limits=RunLimits(spacing=0),
    )
    result = asyncio.run(runner.run())
    assert len(calls) == 3
    assert sum("robots.txt" in value for value in calls) == 1
    assert not any("/notice/" in value for value in calls)
    assert result["completedCount"] == 2
    assert result["requests"] == 3


@pytest.mark.parametrize(
    "status,body", [(403, "denied"), (429, "limited"), (200, "访问过于频繁，请稍后重试"), (200, "请输入验证码后继续访问")]
)
def test_host_restrictions_stop_later_rows_and_resume(tmp_path, status, body):
    calls = []
    path = tmp_path / "private"
    entries = [entry(), entry(3)]
    runner = CatalogRunner(
        entries, path, transport=transport_with(calls, reject=lambda _: httpx.Response(status, text=body)), limits=RunLimits(spacing=0)
    )
    result = asyncio.run(runner.run(limit=1))
    assert result["requests"] == 2
    assert result["completedCount"] == 1
    resumed = CatalogRunner(entries, path, resume=True, transport=transport_with(calls), limits=RunLimits(spacing=0))
    result = asyncio.run(resumed.run())
    assert len(calls) == 2
    assert result["completedCount"] == 2
    assert result["requests"] == 2
    assert resumed.state["results"][entries[1].entry_id]["reason"].startswith("host_blocked:")


def test_html_robots_fails_closed(tmp_path):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="<html><title>首页</title></html>")

    runner = CatalogRunner([entry(), entry(3)], tmp_path / "private", transport=httpx.MockTransport(handle), limits=RunLimits(spacing=0))
    result = asyncio.run(runner.run())
    assert len(calls) == 1
    assert result["requests"] == 1
    assert runner.state["hosts"]["www.example.org"]["blocked"] == "robots_returned_html_unverified"


def test_budget_counts_robots_and_retains_unexecuted_rows(tmp_path):
    calls = []
    runner = CatalogRunner(
        [entry(), entry(3)], tmp_path / "private", transport=transport_with(calls), limits=RunLimits(max_requests=1, spacing=0)
    )
    result = asyncio.run(runner.run())
    assert result["requests"] == 1
    assert len(calls) == 1
    assert result["inputCount"] == 2
    assert result["unexecutedCount"] >= 1
    assert result["complete"] is False


@pytest.mark.parametrize(
    "location,reason",
    [("https://evil.example/notices", "host_not_allowed"), ("http://www.example.org/notices", "redirect_https_downgrade")],
)
def test_redirect_boundary_without_outbound_request(tmp_path, location, reason):
    calls = []
    runner = CatalogRunner(
        [entry()],
        tmp_path / "private",
        transport=transport_with(calls, reject=lambda _: httpx.Response(302, headers={"location": location})),
        limits=RunLimits(spacing=0),
    )
    asyncio.run(runner.run())
    assert len(calls) == 2
    assert runner.state["results"]["main-2"]["reason"] == reason


def test_private_dns_rejected_without_request(tmp_path, monkeypatch):
    monkeypatch.setattr("extrio.source_network.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))])
    calls = []
    runner = CatalogRunner([entry()], tmp_path / "private", transport=transport_with(calls), limits=RunLimits(spacing=0))
    asyncio.run(runner.run())
    assert calls == []
    assert runner.state["results"]["main-2"]["reason"] == "network_address_blocked"


def test_limit_then_resume_never_replays_completed_row(tmp_path):
    calls = []
    path = tmp_path / "private"
    entries = [entry(group="review"), entry(3, group="review")]
    first = CatalogRunner(entries, path, transport=transport_with(calls), limits=RunLimits(spacing=0))
    asyncio.run(first.run(limit=1))
    second = CatalogRunner(entries, path, resume=True, transport=transport_with(calls), limits=RunLimits(spacing=0))
    result = asyncio.run(second.run())
    assert result["requests"] == 3
    assert len(calls) == 3
    assert result["complete"] is True
    with pytest.raises(ValueError, match="fingerprint"):
        CatalogRunner([entry(group="review")], path, resume=True, limits=RunLimits(spacing=0), transport=transport_with(calls))


def test_unknown_error_recorded_not_success_and_no_same_host_retry(tmp_path):
    calls = []

    def fail(request):
        calls.append(str(request.url))
        raise KeyError("unexpected")

    runner = CatalogRunner([entry(), entry(3)], tmp_path / "private", transport=httpx.MockTransport(fail), limits=RunLimits(spacing=0))
    result = asyncio.run(runner.run())
    assert len(calls) == 1
    assert result["requests"] == 1
    assert runner.state["results"]["main-2"]["status"] == "error"
    assert runner.state["results"]["main-2"]["reason"] == "unexpected_error:KeyError"


def test_cancelled_inflight_request_is_counted_and_not_repeated(tmp_path):
    async def handle(request):
        raise asyncio.CancelledError

    path = tmp_path / "private"
    runner = CatalogRunner([entry()], path, transport=httpx.MockTransport(handle), limits=RunLimits(spacing=0))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runner.run())
    ledger = json.loads((path / "ledger.json").read_text())
    assert ledger["requests"] == 1
    assert ledger["results"]["main-2"]["status"] == "interrupted"
    resumed = CatalogRunner([entry()], path, resume=True, limits=RunLimits(spacing=0), transport=httpx.MockTransport(lambda _: None))
    assert asyncio.run(resumed.run())["requests"] == 1


def test_repository_or_symlink_output_rejected(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError, match="repository"):
        CatalogRunner([entry()], repository / "forbidden-catalog-output")
    path = tmp_path / "link"
    path.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        CatalogRunner([entry()], path / "private")


def test_existing_output_needs_resume(tmp_path):
    path = tmp_path / "private"
    CatalogRunner([entry()], path)
    with pytest.raises(ValueError, match="exists"):
        CatalogRunner([entry()], path)


def test_same_host_serial_and_request_spacing(tmp_path):
    started = []
    active = 0
    peak = 0

    async def handle(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.001)
        active -= 1
        return httpx.Response(200, text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else listing())

    runner = CatalogRunner(
        [entry(group="review"), entry(3, group="review")],
        tmp_path / "private",
        transport=httpx.MockTransport(handle),
        limits=RunLimits(spacing=0.025),
    )
    asyncio.run(runner.run())
    assert peak == 1
    assert all(b - a >= 0.02 for a, b in zip(started, started[1:], strict=False))


@pytest.mark.parametrize("candidate_url", ["https://www.example.org:22/notice/1.html", "http://www.example.org/notice/1.html"])
def test_detail_candidates_cannot_use_bad_ports_or_https_downgrade(tmp_path, monkeypatch, candidate_url):
    from tender_sources.catalog import DetailCandidate, ListInspection

    monkeypatch.setattr(
        "tender_sources.catalog_run.inspect_list",
        lambda *_: ListInspection(
            "采购公告",
            "candidate_list",
            "dated_notice_links",
            [DetailCandidate(candidate_url, "测试采购公告", "2026-10-20", "fixture")],
        ),
    )
    calls = []
    runner = CatalogRunner([entry()], tmp_path / "private", transport=transport_with(calls), limits=RunLimits(spacing=0))
    asyncio.run(runner.run())
    assert len(calls) == 2
    assert runner.state["results"]["main-2"]["status"] == "needs_adapter"


def test_code_changes_cannot_silently_resume(tmp_path):
    path = tmp_path / "private"
    runner = CatalogRunner([entry()], path, limits=RunLimits(spacing=0), transport=httpx.MockTransport(lambda _: None))
    runner.state["codeSha256"]["catalog_run.py"] = "different_code"
    runner.persist()
    runner.close()
    with pytest.raises(ValueError, match="code fingerprint"):
        CatalogRunner([entry()], path, resume=True, limits=RunLimits(spacing=0), transport=httpx.MockTransport(lambda _: None))


def test_live_mode_cannot_relax_limits(tmp_path):
    with pytest.raises(ValueError, match="limits"):
        CatalogRunner([entry()], tmp_path / "private", limits=RunLimits(spacing=0))
    with pytest.raises(ValueError, match="limits"):
        CatalogRunner([entry()], tmp_path / "private2", limits=replace(RunLimits(), max_requests=8001))


def test_dot_dot_repository_output_rejected():
    repository = Path(__file__).resolve().parents[2]
    indirect = Path("/private/tmp/../..") / repository.relative_to("/") / "forbidden-catalog-output"
    with pytest.raises(ValueError, match="repository"):
        CatalogRunner([entry()], indirect)


def test_csv_export_escapes_formulas_and_retains_historical_date(tmp_path):
    row = replace(entry(), name='=HYPERLINK("bad")', metadata={"sourceId": "+source", "checkedOn": "2026-10-10"})
    runner = CatalogRunner([row], tmp_path / "private")
    asyncio.run(runner.run(dry_run=True))
    exported = (runner.output / "matrix.csv").read_text()
    assert "'=HYPERLINK" in exported
    assert "'+source" in exported
    assert "2026-10-10" in exported
    assert json.loads((runner.output / "rows.jsonl").read_text())["name"] == row.name


def test_only_one_writer_can_own_run(tmp_path):
    path = tmp_path / "private"
    first = CatalogRunner([entry()], path)
    with pytest.raises(ValueError, match="locked"):
        CatalogRunner([entry()], path, resume=True)
    asyncio.run(first.run(dry_run=True))


def test_byte_budget_and_timeout_still_account_inflight_request(tmp_path):
    calls = []
    runner = CatalogRunner(
        [entry(), entry(3)], tmp_path / "bytes", transport=transport_with(calls), limits=RunLimits(spacing=0, max_bytes=10)
    )
    result = asyncio.run(runner.run())
    assert result["requests"] == 1
    assert result["bytes"] > 10
    assert result["stopReason"] == "batch_bytes_budget_exceeded"
    assert result["complete"] is False

    async def wait(request):
        await asyncio.sleep(2)

    timed = CatalogRunner(
        [entry()], tmp_path / "timeout", transport=httpx.MockTransport(wait), limits=RunLimits(spacing=0, row_seconds=0.2)
    )
    result = asyncio.run(timed.run())
    assert result["requests"] == 1
    assert timed.state["results"]["main-2"]["reason"] == "row_duration_exceeded"
    trace = json.loads(next((timed.output / "traces").glob("*.json")).read_text())
    assert trace["outcome"] == "cancelled"


def test_robots_deny_and_network_failure_are_shared_terminal_blocks(tmp_path):
    calls = []

    def deny(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    runner = CatalogRunner([entry(), entry(3)], tmp_path / "deny", transport=httpx.MockTransport(deny), limits=RunLimits(spacing=0))
    asyncio.run(runner.run())
    assert len(calls) == 1
    assert runner.state["results"]["main-3"]["status"] == "inherited_block"

    def disconnected(request):
        calls.append(str(request.url))
        raise httpx.ConnectError("offline")

    failed = CatalogRunner(
        [entry(), entry(3)], tmp_path / "failed", transport=httpx.MockTransport(disconnected), limits=RunLimits(spacing=0)
    )
    asyncio.run(failed.run())
    assert failed.state["requests"] == 1
    assert failed.state["results"]["main-2"]["reason"] == "source_connection_failed"
    assert failed.state["results"]["main-3"]["status"] == "inherited_block"


def test_robots_redirect_to_html_fails_closed(tmp_path):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(302, headers={"location": "/home"})
        return httpx.Response(200, text="<html><title>首页</title><body>欢迎</body></html>")

    runner = CatalogRunner([entry(), entry(3)], tmp_path / "private", transport=httpx.MockTransport(handle), limits=RunLimits(spacing=0))
    asyncio.run(runner.run())
    assert len(calls) == 2
    assert runner.state["hosts"]["www.example.org"]["blocked"] == "robots_returned_html_unverified"


def test_redirect_cannot_escape_to_unapproved_port(tmp_path):
    calls = []
    runner = CatalogRunner(
        [entry()],
        tmp_path / "private",
        transport=transport_with(
            calls,
            reject=lambda _: httpx.Response(302, headers={"location": "https://www.example.org:8443/x"}),
        ),
        limits=RunLimits(spacing=0),
    )
    asyncio.run(runner.run())
    assert len(calls) == 2


def test_hidden_challenge_template_and_notice_help_do_not_block(tmp_path):
    calls = []
    body = (
        listing()
        + '<script>var msg="请输入验证码，请稍后重试";</script><div hidden>请输入验证码</div><p>帮助：若访问频率过高请稍后重试</p>'
    )
    runner = CatalogRunner(
        [entry(group="review"), entry(3, group="review")],
        tmp_path / "private",
        transport=transport_with(
            calls,
            reject=lambda _: httpx.Response(200, text=body),
        ),
        limits=RunLimits(spacing=0),
    )
    asyncio.run(runner.run())
    assert len(calls) == 3
    assert runner.state["hosts"]["www.example.org"]["blocked"] is None


def test_tls_compatibility_attempts_have_shared_spacing_and_count(tmp_path):
    started = []

    def handle(request):
        started.append(time_value := time.monotonic())
        assert time_value > 0
        if len(started) == 1:
            cause = ssl.SSLError(1, "BAD_ECPOINT")
            cause.reason = "BAD_ECPOINT"
            error = httpx.ConnectError("handshake")
            error.__cause__ = cause
            raise error
        return httpx.Response(200, text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else listing())

    runner = CatalogRunner(
        [entry(group="review")], tmp_path / "private", transport=httpx.MockTransport(handle), limits=RunLimits(spacing=0.025)
    )
    result = asyncio.run(runner.run())
    assert result["requests"] == 3
    assert all(b - a >= 0.02 for a, b in zip(started, started[1:], strict=False))


def test_gbk_challenge_page_stops_host(tmp_path):
    calls = []
    runner = CatalogRunner(
        [entry(group="review"), entry(3, group="review")],
        tmp_path / "private",
        transport=transport_with(
            calls,
            reject=lambda _: httpx.Response(
                200, content="<p>请输入验证码后继续访问</p>".encode("gbk"), headers={"content-type": "text/html;charset=gbk"}
            ),
        ),
        limits=RunLimits(spacing=0),
    )
    asyncio.run(runner.run())
    assert len(calls) == 2
    assert runner.state["hosts"]["www.example.org"]["blocked"] == "access_challenge"


def test_distinct_hosts_have_at_most_four_active_requests(tmp_path):
    active = peak = 0

    async def handle(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, text="User-agent: *\nAllow: /" if request.url.path == "/robots.txt" else listing())

    entries = [entry(number, group="review", host=f"host{number}.example.org") for number in range(10)]
    runner = CatalogRunner(entries, tmp_path / "private", transport=httpx.MockTransport(handle), limits=RunLimits(spacing=0))
    result = asyncio.run(runner.run())
    assert peak == 4
    assert result["requests"] == 20


def test_batch_deadline_cancels_inflight_request(tmp_path):
    async def wait(request):
        await asyncio.sleep(2)

    runner = CatalogRunner(
        [entry()], tmp_path / "private", transport=httpx.MockTransport(wait), limits=RunLimits(spacing=0, max_seconds=0.2)
    )
    before = time.monotonic()
    result = asyncio.run(runner.run())
    assert time.monotonic() - before < 1
    assert result["requests"] == 1
    assert result["stopReason"] == "batch_duration_exceeded"


def test_review_actual_request_cap_includes_redirects(tmp_path):
    calls = []
    runner = CatalogRunner(
        [entry(group="review")],
        tmp_path / "private",
        transport=transport_with(
            calls,
            reject=lambda request: httpx.Response(302, headers={"location": "/redirect"}),
        ),
        limits=RunLimits(spacing=0),
    )
    result = asyncio.run(runner.run())
    assert result["requests"] == len(calls) == 3
    assert runner.state["results"]["review-2"]["reason"] == "row_request_budget_exceeded"


@pytest.mark.parametrize("content_type", ["text/html; charset=utf-8", ""])
def test_robots_html_fragment_fails_closed(tmp_path, content_type):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"<div>Service unavailable</div>", headers={"content-type": content_type})

    runner = CatalogRunner([entry()], tmp_path / "private", transport=httpx.MockTransport(handle), limits=RunLimits(spacing=0))
    asyncio.run(runner.run())
    assert len(calls) == 1
    assert runner.state["results"]["main-2"]["reason"] == "robots_returned_html_unverified"


def test_cancel_then_resume_blocks_other_rows_on_same_host(tmp_path):
    async def cancel(request):
        raise asyncio.CancelledError

    path = tmp_path / "private"
    entries = [entry(), entry(3)]
    runner = CatalogRunner(entries, path, transport=httpx.MockTransport(cancel), limits=RunLimits(spacing=0))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runner.run(limit=1))
    calls = []
    resumed = CatalogRunner(entries, path, resume=True, transport=transport_with(calls), limits=RunLimits(spacing=0))
    result = asyncio.run(resumed.run())
    assert not result["complete"]
    assert calls == []
    assert result["requests"] == 1
    assert resumed.state["results"]["main-3"]["status"] == "inherited_block"


@pytest.mark.parametrize("hidden_style", ["display:none", "visibility:hidden"])
@pytest.mark.parametrize("visible_challenge", [False, True])
def test_nested_styled_challenge_nodes_do_not_fail_or_hide_visible_gate(hidden_style, visible_challenge):
    hidden = f'<div style="{hidden_style}"><span style="color:red">请输入验证码</span></div>'
    visible = "<p>请输入验证码后继续访问</p>" if visible_challenge else listing()
    assert _challenge((hidden + visible).encode(), entry().entry_url) is visible_challenge


def test_normal_nested_styled_notice_is_not_a_challenge():
    html = '<div style="padding:4px"><section style="color:black">' + listing() + "</section></div>"
    assert not _challenge(html.encode(), entry().entry_url)


@pytest.mark.parametrize("visible_challenge", [False, True])
def test_nested_hidden_styles_end_to_end_keep_normal_rows_and_stop_visible_gate(tmp_path, visible_challenge):
    calls = []
    hidden = '<div style="display:none"><span style="visibility:hidden">请输入验证码</span></div>'
    visible = "<p>请输入验证码后继续访问</p>" if visible_challenge else listing()
    runner = CatalogRunner(
        [entry(group="review"), entry(3, group="review")],
        tmp_path / "private",
        transport=transport_with(calls, reject=lambda _: httpx.Response(200, text=hidden + visible)),
        limits=RunLimits(spacing=0),
    )
    result = asyncio.run(runner.run())
    statuses = [row["status"] for row in runner.state["results"].values()]
    assert "error" not in statuses
    assert result["requests"] == len(calls) == (2 if visible_challenge else 3)
    if visible_challenge:
        assert statuses == ["restricted", "inherited_block"]
        assert runner.state["hosts"]["www.example.org"]["blocked"] == "access_challenge"
    else:
        assert "inherited_block" not in statuses
        assert runner.state["hosts"]["www.example.org"]["blocked"] is None
