"""Explicit review sampling and shared template gates for isolated catalog work."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.catalog import CatalogEntry, DetailCandidate, inspect_detail, inspect_list  # noqa: E402
from tender_sources.catalog_run import CatalogRunner, RunLimits  # noqa: E402

URL = "https://cgzx.zjnu.edu.cn/2026/1020/c20381a12345/page.htm"
TITLE = "测试设备采购项目公开招标公告"
BODY = "本项目采购设备公开招标，投标人应按要求提交投标材料并满足采购需求。" * 20


def zjnu_html(*, title=TITLE, date="2026-10-20", body=BODY):
    return (
        '<div id="mainWraper"><div class="listMain"><div class="info-box"><div class="article">'
        f'<h1 class="arti-title">{title}</h1><p class="arti-metas"><span class="arti-update">'
        f'<span id="time">{date}</span></span></p><div class="entry"><article class="read">'
        f'<div class="wp_articlecontent">{body}</div></article></div></div></div></div></div>'
    )


def test_exact_template_has_truthful_identity_and_shared_gates():
    result = inspect_detail(zjnu_html(), URL, DetailCandidate(URL, TITLE, "2026-10-20", "static_notice_link+row_date"))
    assert result["status"] == "sample_readable"
    assert result["templateId"] == "zjnu"
    assert result["contentMode"] == "html_template_candidate"


def test_zjnu_chinese_chrome_publication_field_cannot_pass_global_gate():
    html = zjnu_html().replace('id="time"', 'id="time" class="版权"')
    result = inspect_detail(html, URL, DetailCandidate(URL, TITLE, "2026-10-20", "static_notice_link+row_date"))
    assert result["status"] != "sample_readable"
    assert result["reason"] == "missing_publication_date"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"title": "其他采购项目招标公告"}, "title_mismatch"),
        ({"date": ""}, "missing_publication_date"),
        ({"date": "2099-10-20"}, "missing_publication_date"),
        ({"body": '<iframe src="/a.pdf"></iframe>'}, "pdf_requires_adapter"),
        ({"body": "<a href='/x'>采购招标公告</a>" * 30}, "navigation_or_link_only_body"),
    ],
)
def test_template_does_not_bypass_global_quality(kwargs, reason):
    result = inspect_detail(zjnu_html(**kwargs), URL, DetailCandidate(URL, TITLE, "2026-10-20", "static_notice_link+row_date"))
    assert result["status"] != "sample_readable"
    assert result["reason"] == reason


def row(identifier="review:2", group="review"):
    return CatalogEntry(identifier, group, 2, "https://example.org/notices", "source", {})


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("extrio.source_network.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))])


def network(calls):
    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path.startswith("/detail"):
            return httpx.Response(200, text=f'<h1>{TITLE}</h1><time datetime="2026-10-20"></time><article>{BODY}</article>')
        return httpx.Response(
            200,
            text=(
                f'<ul><li><a href="/detail1">{TITLE}</a><span>2026-10-20</span></li>'
                f'<li><a href="/detail2">{TITLE}</a><span>2026-10-20</span></li></ul>'
            ),
        )

    return httpx.MockTransport(handle)


def test_default_review_does_not_fetch_details(tmp_path):
    calls = []
    runner = CatalogRunner([row()], tmp_path / "default", transport=network(calls), limits=RunLimits(spacing=0))
    asyncio.run(runner.run(entry_ids={"review:2"}))
    assert calls == ["/robots.txt", "/notices"]


def test_review_optin_samples_two_details_and_persists_policy(tmp_path):
    calls = []
    runner = CatalogRunner(
        [row()], tmp_path / "sample", transport=network(calls), limits=RunLimits(spacing=0), sample_review_entry_ids={"review:2"}
    )
    summary = asyncio.run(runner.run(entry_ids={"review:2"}))
    assert calls == ["/robots.txt", "/notices", "/detail1", "/detail2"]
    assert runner.state["results"]["review:2"]["status"] == "sample_readable"
    assert runner.state["results"]["review:2"]["samplingScope"] == "review_detail_samples"
    assert summary["samplingPolicy"]["sampleReviewEntryIds"] == ["review:2"]


@pytest.mark.parametrize("identifiers", [{"main:2"}, {"unknown"}])
def test_scope_rejects_nonreview_or_unknown_ids(tmp_path, identifiers):
    with pytest.raises(ValueError, match="review"):
        CatalogRunner([row(), row("main:2", "main")], tmp_path / "bad", sample_review_entry_ids=identifiers)


def test_scope_requires_explicit_current_selection_and_resume_cannot_erase(tmp_path):
    calls = []
    path = tmp_path / "sample"
    runner = CatalogRunner([row()], path, transport=network(calls), limits=RunLimits(spacing=0), sample_review_entry_ids={"review:2"})
    with pytest.raises(ValueError, match="explicit"):
        asyncio.run(runner.run())
    with pytest.raises(ValueError, match="sampling"):
        CatalogRunner([row()], path, resume=True, transport=network(calls), limits=RunLimits(spacing=0), sample_review_entry_ids=set())
    resumed = CatalogRunner([row()], path, resume=True, transport=network(calls), limits=RunLimits(spacing=0))
    assert resumed.state["samplingPolicy"]["sampleReviewEntryIds"] == ["review:2"]
    asyncio.run(resumed.run(entry_ids={"review:2"}))


def test_saved_sampling_policy_cannot_be_tampered_or_choose_unknown_ids(tmp_path):
    path = tmp_path / "sample"
    runner = CatalogRunner([row()], path, sample_review_entry_ids={"review:2"})
    asyncio.run(runner.run(dry_run=True, entry_ids={"review:2"}))
    state = json.loads((path / "ledger.json").read_text())
    state["samplingPolicy"]["sampleReviewEntryIds"] = []
    (path / "ledger.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="sampling"):
        CatalogRunner([row()], path, resume=True)


def test_dependency_fingerprints_include_actual_parsing_sources(tmp_path):
    runner = CatalogRunner([row()], tmp_path / "private")
    asyncio.run(runner.run(dry_run=True))
    code = runner.state["codeSha256"]
    for name in [
        "catalog_template_university.py",
        "catalog_template_henan.py",
        "catalog_template_zjnu.py",
        "adapters.py",
        "extrio/source_network.py",
        "extrio/harvest.py",
    ]:
        assert name in code
    state = json.loads((runner.output / "ledger.json").read_text())
    state["codeSha256"]["adapters.py"] = "0" * 64
    (runner.output / "ledger.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="code fingerprint"):
        CatalogRunner([row()], runner.output, resume=True)


@pytest.mark.parametrize("optin,expected", [(False, 3), (True, 12)])
def test_review_diagnostic_three_requests_but_explicit_sampling_twelve(tmp_path, optin, expected):
    calls = []

    def handle(request):
        path = request.url.path
        calls.append(path)
        chains = {
            "/robots.txt": "/policy1",
            "/policy1": "/policy2",
            "/notices": "/list1",
            "/list1": "/list2",
            "/detail1": "/d1a",
            "/d1a": "/d1b",
            "/detail2": "/d2a",
            "/d2a": "/d2b",
        }
        if path in chains:
            return httpx.Response(302, headers={"location": chains[path]})
        if path == "/policy2":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if path == "/list2":
            return httpx.Response(
                200,
                text=(
                    f'<ul><li><a href="/detail1">{TITLE}</a><span>2026-10-20</span></li>'
                    f'<li><a href="/detail2">{TITLE}</a><span>2026-10-20</span></li></ul>'
                ),
            )
        return httpx.Response(200, text=f'<h1>{TITLE}</h1><time datetime="2026-10-20"></time><article>{BODY}</article>')

    runner = CatalogRunner(
        [row()],
        tmp_path / "sample",
        transport=httpx.MockTransport(handle),
        limits=RunLimits(spacing=0),
        sample_review_entry_ids={"review:2"} if optin else None,
    )
    summary = asyncio.run(runner.run(entry_ids={"review:2"}))
    assert summary["requests"] == len(calls) == expected
    assert runner.state["results"]["review:2"]["requests"] == expected


def university_html(*, title=TITLE, date="2026-10-20", body=BODY):
    return (
        f'<div class="wrap"><div class="cright"><div class="ctitle"><h1>{title}</h1>'
        f'<div class="info"><i>发布日期：{date}</i></div></div><div class="ccontent">{body}</div></div></div>'
    )


def henan_html(*, title=TITLE, date="2026-10-20", body=BODY):
    return (
        f'<div class="container box"><div class="box-con"><div class="box-header">{title}</div>'
        '<div class="browse"><div class="browse-main">'
        f'<span class="browse-item">发布时间：{date}</span></div></div><div class="box-content">'
        f'<div class="box-infor"><div id="infoContentM" class="box-article">{body}</div></div></div></div></div>'
    )


TEMPLATES = [
    ("university", "https://nkzbb.nankai.edu.cn/cghw/1234.chtml", university_html),
    ("henan", "https://ggzyjyzx.neixiangxian.gov.cn/jyxx/002001/002001005/20261020/11111111-2222-4333-8444-555555555555.html", henan_html),
    ("zjnu", URL, zjnu_html),
]


@pytest.mark.parametrize("template_id,url,markup", TEMPLATES)
@pytest.mark.parametrize("case", ["valid", "future", "pdf", "navigation"])
def test_all_templates_share_unchanged_quality_gate(template_id, url, markup, case):
    kwargs = {}
    if case == "future":
        kwargs["date"] = "2099-10-20"
    elif case == "pdf":
        kwargs["body"] = '<iframe src="/body.pdf"></iframe>'
    elif case == "navigation":
        kwargs["body"] = '<a href="/other">采购项目招标公告导航</a>' * 30
    result = inspect_detail(markup(**kwargs), url, DetailCandidate(url, TITLE, "2026-10-20", "static_notice_link+row_date"))
    assert result["templateId"] == template_id
    assert (result["status"] == "sample_readable") is (case == "valid")
    if case != "valid":
        assert (
            result["reason"]
            == {"future": "missing_publication_date", "pdf": "pdf_requires_adapter", "navigation": "navigation_or_link_only_body"}[case]
        )


@pytest.mark.parametrize("bad_scope", ["unknown_host", "unknown_dom", "known"])
def test_henan_list_title_date_fields_remain_separate_only_in_exact_template(bad_scope):
    url = "https://ggzyjyzx.neixiangxian.gov.cn/jyxx/002001/002001005/transaction.html"
    detail = "/jyxx/002001/002001005/20261020/11111111-2222-4333-8444-555555555555.html"
    html = (
        '<div class="container box"><div class="box-con public-box"><div class="public-con">'
        '<div class="box-content"><div id="info-list" class="public-list">'
        f'<a class="public-list-item" href="{detail}"><span class="item-title">{TITLE}</span>'
        '<span class="item-date">2026-10-20</span></a></div></div></div></div></div>'
    )
    if bad_scope == "unknown_host":
        url = url.replace("ggzyjyzx.neixiangxian.gov.cn", "unknown.example.org")
    elif bad_scope == "unknown_dom":
        html = html.replace('class="public-con"', 'class="other-con"')
    result = inspect_list(html, url)
    assert result.candidates
    candidate = result.candidates[0]
    assert candidate.published_at == "2026-10-20"
    assert (candidate.title == TITLE) is (bad_scope == "known")
    if bad_scope == "known":
        inspected = inspect_detail(henan_html(), candidate.url, candidate)
        assert inspected["status"] == "sample_readable"
