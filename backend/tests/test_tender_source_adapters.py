"""Offline contracts for the opt-in, isolated tender source test driver."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.adapters import (  # noqa: E402
    PROFILES,
    Detail,
    agency_resource,
    canonical_url,
    notice_stage_from_url,
    parse_agency_data,
    parse_detail,
    parse_list,
    sample_records,
    validate_detail,
)
from tender_sources.run import Sampler, run_source  # noqa: E402
from tender_sources.summarize import assemble  # noqa: E402

from extrio.source_network import SourceNetworkError, SourceResponse  # noqa: E402


def test_csg_full_attribute_not_truncated_text_or_category():
    html = (
        '<div class="List2"><ul><li><span class="Right"><a href="/zbgg/index.jhtml">公告</a>'
        '<span class="Gray">2026-10-16</span></span>'
        '<a target="_blank" title="采购项目完整标题公告" href="/zbgg/123.jhtml">采购项目...</a></li></ul></div>'
    )
    page = parse_list("csg", html, PROFILES["csg"].entry)
    assert page.records[0]["listTitle"] == "采购项目完整标题公告"
    assert page.records[0]["detailUrl"].endswith("/zbgg/123.jhtml")


def test_csg_full_title_can_be_in_another_anchor_for_the_same_exact_url():
    html = (
        '<div class="List2"><ul><li><span class="Right"><span class="Gray">2026-10-16</span></span>'
        '<a target="_blank" href="/zbgg/123.jhtml">项目...</a></li></ul></div>'
        '<a href="/zbgg/123.jhtml" title="项目完整名称公告">项目...</a>'
    )
    record = parse_list("csg", html, PROFILES["csg"].entry).records[0]
    assert record["listTitle"] == "项目完整名称公告"
    assert record["titleEvidence"] == "same_url_title_attribute"


def test_csg_no_full_title_does_not_invent_one():
    html = '<div class="List2"><ul><li><a target="_blank" href="/zbgg/123.jhtml">项目...</a></li></ul></div>'
    assert parse_list("csg", html, PROFILES["csg"].entry).records[0]["listTitle"] == "项目..."


@pytest.mark.parametrize("current,path,next_path", [(0, "", "index_1.htm"), (1, "index_1.htm", "index_2.htm")])
def test_ccgp_static_pager_is_parsed_without_javascript(current, path, next_path):
    html = f"<script>Pager({{size:25, current:{current}, prefix:'index',suffix:'htm'}});</script>"
    page = parse_list("ccgp", html, PROFILES["ccgp"].entry + path)
    assert page.next_url == PROFILES["ccgp"].entry + next_path


@pytest.mark.parametrize(
    "script",
    [
        "Pager({size:25,current:0,prefix:'https://evil.test/x',suffix:'htm'});",
        "Pager({size:25,current:0,prefix:getPrefix(),suffix:'htm'});",
        "Pager({size:1,current:0,prefix:'index',suffix:'htm'});",
        "Pager({size:25,current:5,prefix:'index',suffix:'htm'});",
    ],
)
def test_ccgp_pager_fails_closed_on_unknown_or_inconsistent_configuration(script):
    assert parse_list("ccgp", f"<script>{script}</script>", PROFILES["ccgp"].entry).next_url is None


def test_xmu_get_form_pagination_keeps_the_column():
    html = '<div id="datab"><dd><a href="/cghw/1.chtml" title="项目">项目</a><span class="date">2026-10-16</span></dd></div>'
    html += '<input id="hcurPage" value="2"><input id="rowTotal" value="173">'
    page = parse_list("xmu", html, PROFILES["xmu"].entry + "?curPage=2")
    assert page.next_url == PROFILES["xmu"].entry + "?curPage=3"


def test_hospital_public_pagination_api_uses_item_date():
    html = "<script>pagedata('1675','193','pageBox','list','articles',10);</script>"
    assert parse_list("hospital", html, PROFILES["hospital"].entry).next_url.endswith("page=2&cid=193&cur=10")
    data = {"code": 1, "data": {"list": [{"id": 10332, "category_id": 193, "title": "项目公告", "public_time": "2026-10-06"}]}}
    page = parse_list("hospital", json.dumps(data), "https://www.zy91.com/content/get_article?page=2&cid=193&cur=10")
    assert page.records[0]["detailUrl"] == "https://www.zy91.com/content/default/193/10332"
    assert page.records[0]["listPublishedAt"] == "2026-10-06"
    assert "page=3" in page.next_url


def test_hospital_api_rejects_another_category():
    data = {"code": 1, "data": {"list": [{"id": 1, "category_id": 77, "title": "新闻", "public_time": "2026-10-06"}]}}
    with pytest.raises(ValueError, match="category"):
        parse_list("hospital", json.dumps(data), "https://www.zy91.com/content/get_article?page=2&cid=193&cur=10")


def test_fudan_literal_next_link_and_pdf_body():
    page = parse_list("fudan", '<a class="next" href="/cggg/list2.htm">下一页</a>', PROFILES["fudan"].entry)
    assert page.next_url.endswith("/cggg/list2.htm")
    detail = parse_detail(
        "fudan",
        '<h1 class="arti_title">公告</h1><span class="arti_update">2026-10-16</span>'
        '<div class="wp_articlecontent"><iframe src="/file.pdf"></iframe></div>',
        PROFILES["fudan"].entry,
    )
    assert detail.pdf_urls == ["https://czzx.fudan.edu.cn/file.pdf"]
    assert not detail.content


def test_xmu_official_pointer_not_a_complete_notice():
    html = (
        '<div class="ctitle"><h1>设备采购信息</h1><div class="info"><i>2026-10-16</i></div></div>'
        '<div class="ccontent">中国政府采购网公告链接：<a href="https://www.ccgp.gov.cn/cggg/zygg/gkzb/202610/t1.htm">原文</a></div>'
    )
    detail = parse_detail("xmu", html, PROFILES["xmu"].entry)
    assert detail.original_urls == ["https://www.ccgp.gov.cn/cggg/zygg/gkzb/202610/t1.htm"]
    assert validate_detail(detail, {"listTitle": "设备采购信息", "listPublishedAt": "2026-10-16"}) == "original_not_resolved"


def test_agency_iframe_is_a_resource_not_body():
    html = '<iframe id="iframepage" src="https://eps.gdebidding.com/view?guid=one"></iframe>'
    detail = parse_detail("agency", html, PROFILES["agency"].entry)
    assert detail.frame_url == "https://eps.gdebidding.com/view?guid=one"
    assert not detail.content


def test_agency_resource_requires_the_exact_public_template_and_literal_endpoint():
    guid = "deabe3bd-a824-4422-9db8-5fcdc0218b17"
    url = "https://eps.gdebidding.com/gdjd-xunjia/gonggaoxinxi/gongGao_view.html?guid=" + guid
    endpoint = "/gdjd-xunjia/gonggaoxinxi/queryXiangMuByGuid.do?guid="
    assert agency_resource(url, f"url: '{endpoint}' + guid")[0].endswith("queryXiangMuByGuid.do?guid=" + guid)
    with pytest.raises(ValueError, match="template"):
        agency_resource(url, "")


def test_agency_identity_requires_both_guid_and_exact_project_notice_variant():
    data = {
        "xiangMuGuid": "one",
        "xiangMuName": "工程维修项目",
        "caiGouType": 4,
        "gongGaoStartTimeText": "2026-10-16 09:00:00",
        "creatorName": "not_public",
        "accountName": "not_public",
    }
    record = {"listTitle": "工程维修项目竞价公告"}
    detail = parse_agency_data(data, record, "one", result=False)
    assert validate_detail(detail, record) is None
    assert "not_public" not in detail.content
    other = {"listTitle": "工程维修项目的其他采购竞价公告"}
    assert validate_detail(parse_agency_data(data, other, "one", result=False), other) == "title_mismatch"
    with pytest.raises(ValueError, match="guid"):
        parse_agency_data(data, record, "another", result=False)


def test_agency_result_respects_visibility_and_package_code():
    data = {
        "jieGuoGuid": "one",
        "xiangMu": {"xiangMuName": "采购项目", "caiGouTypeText": "竞价采购"},
        "baoJian": {"baoJianBianHao": "JJCG-1/01"},
        "gongShiFaBuTimeShortText": "2026-10-16",
    }
    record = {"listTitle": "采购项目(包件01)成交结果公告"}
    assert validate_detail(parse_agency_data(data, record, "one", result=True), record) is None
    other = {"listTitle": "采购项目(包件02)成交结果公告"}
    assert validate_detail(parse_agency_data(data, other, "one", result=True), other) == "title_mismatch"
    with pytest.raises(ValueError, match="visibility"):
        parse_agency_data({**data, "hideForBidder": True}, record, "one", result=True)


def test_title_mismatch_still_rejected():
    html = '<h2 class="tc">另一个项目</h2><span id="pubTime">2026-10-16</span><div class="vF_detail_content">正文</div>'
    detail = parse_detail("ccgp", html, PROFILES["ccgp"].entry)
    assert validate_detail(detail, {"listTitle": "项目公告", "listPublishedAt": "2026-10-16"}) == "title_mismatch"


@pytest.mark.parametrize("url", ["https://evil.test/1", "https://user:pw@www.ccgp.gov.cn/a", "javascript:alert(1)", "file:///tmp/a"])
def test_url_scope_is_exact_and_credential_free(url):
    with pytest.raises(ValueError):
        canonical_url(url, PROFILES["ccgp"])


def test_fragments_deduplicate_but_distinct_query_ids_do_not():
    p = PROFILES["agency"]
    assert canonical_url("https://eps.gdebidding.com/gg?guid=1#top", p).endswith("guid=1")
    assert canonical_url("https://eps.gdebidding.com/gg?guid=1", p) != canonical_url("https://eps.gdebidding.com/gg?guid=2", p)


def test_sampling_spans_all_pages_without_duplicates():
    pages = [[{"detailUrl": f"https://source.test/{page}/{i}"} for i in range(10)] for page in range(3)]
    pages[1][0] = pages[0][0]
    rows = sample_records(pages, 20)
    assert len(rows) == len({r["detailUrl"] for r in rows}) == 20
    assert {r["detailUrl"].split("/")[-2] for r in rows} == {"0", "1", "2"}


def test_csg_truncated_title_requires_long_prefix_matching_date_and_breadcrumb():
    title = "采购项目招标公告的超长项目名称" * 5
    detail = Detail(title=title, content="正文", published_at="2026-10-16", fields={"breadcrumbTitle": title})
    record = {"listTitle": title[:50] + "...", "listPublishedAt": "2026-10-16"}
    assert validate_detail(detail, record) == "title_mismatch"
    assert validate_detail(detail, record, source_id="csg") is None
    assert validate_detail(detail, {**record, "listPublishedAt": "2026-10-15"}, source_id="csg") == "title_mismatch"
    assert validate_detail(detail, {**record, "listTitle": "采购..."}, source_id="csg") == "title_mismatch"
    detail.fields["breadcrumbTitle"] = "无关项目"
    assert validate_detail(detail, record, source_id="csg") == "title_mismatch"


def test_ccgp_structured_project_and_buyer_corroborate_a_linked_original():
    html = (
        '<div class="table"><table><tr><td class="title">采购项目名称</td><td>厦门大学设备</td></tr>'
        '<tr><td class="title">采购单位</td><td>厦门大学</td></tr></table></div>'
    )
    original = parse_detail("ccgp", html, "https://www.ccgp.gov.cn/cggg/zygg/gkzb/one.htm")
    assert Sampler.original_title_matches("厦门大学设备采购信息", original)
    assert not Sampler.original_title_matches("厦门大学其他设备采购信息", original)
    assert not Sampler.original_title_matches("厦门大学设备采购更正信息", original)
    original.fields["buyer"] = "其他单位"
    assert not Sampler.original_title_matches("厦门大学设备采购信息", original)


def test_ccgp_stage_must_be_an_explicitly_recognized_column():
    assert notice_stage_from_url("https://www.ccgp.gov.cn/cggg/zygg/gzgg/202610/t1.htm") == "correction"
    assert notice_stage_from_url("https://www.ccgp.gov.cn/cggg/zygg/gkzb/202610/t1.htm") == "procurement"
    assert notice_stage_from_url("https://www.ccgp.gov.cn/cggg/zygg/unknown/202610/t1.htm") is None


@pytest.mark.asyncio
async def test_publisher_http_redirect_is_only_retried_as_exact_https():
    sampler = Sampler("fudan")
    requested = []
    initial = "https://czzx.fudan.edu.cn/_redirect?articleId=1"
    secure = "https://www.ccgp.gov.cn/cggg/one.htm"

    async def fetch(url, **kwargs):
        requested.append(url)
        if url == initial:
            sampler.network.trace.append({"url": url, "location": "http://www.ccgp.gov.cn/cggg/one.htm"})
            raise SourceNetworkError("redirect_https_downgrade")
        assert url == secure
        return SourceResponse(url, 200, {}, b"notice")

    sampler.network.fetch = fetch
    assert (await sampler.fetch(initial)).url == secure
    assert requested == [initial, secure]


@pytest.mark.asyncio
async def test_unknown_host_in_publisher_redirect_is_not_upgraded_or_followed():
    sampler = Sampler("fudan")

    async def fetch(url, **kwargs):
        sampler.network.trace.append({"url": url, "location": "http://evil.test/cggg/one.htm"})
        raise SourceNetworkError("redirect_https_downgrade")

    sampler.network.fetch = fetch
    with pytest.raises(SourceNetworkError, match="downgrade"):
        await sampler.fetch("https://czzx.fudan.edu.cn/_redirect?articleId=1")


def test_pdf_magic_checked_before_importing_optional_parser():
    helper = Path(__file__).resolve().parents[2] / "scripts/tender_sources/pdf_text.py"
    result = subprocess.run([sys.executable, str(helper)], input=b"<html>not a PDF</html>", capture_output=True, timeout=5)
    assert result.returncode != 0
    assert b"invalid_or_oversized_pdf" in result.stderr


@pytest.mark.asyncio
async def test_access_denial_stops_the_source_before_other_details(monkeypatch, tmp_path):
    requested = []

    async def html(self, url):
        requested.append(url)
        if url == self.profile.entry:
            return url, (
                '<ul class="c_list_bid"><li><a href="/a.htm" title="项目一">项目一</a><em>2026-10-16</em></li>'
                '<li><a href="/b.htm" title="项目二">项目二</a><em>2026-10-16</em></li></ul>'
            )
        raise SourceNetworkError("authentication_or_access_required")

    monkeypatch.setattr(Sampler, "html", html)
    args = SimpleNamespace(pdf_python=None, ocr_command=None, pdftoppm=None, output=tmp_path, pages=1, details=20, content_dir=None)
    report = await run_source("ccgp", args)
    assert report["summary"]["attempted"] == 1
    assert len(requested) == 2
    assert report["errors"][0]["reason"] == "authentication_or_access_required"


@pytest.mark.asyncio
async def test_even_confident_ocr_text_requires_manual_review(monkeypatch):
    sampler = Sampler("fudan")
    html = (
        '<h1 class="arti_title">设备公告</h1><span class="arti_update">2026-10-16</span>'
        '<div class="wp_articlecontent"><iframe src="/body.pdf"></iframe></div>'
    )

    async def get_html(url):
        return url, html

    async def get_pdf(url):
        return {"text": "OCR extracted text", "pages": 1, "extraction": "ocr", "reviewRequired": True, "minimumLineConfidence": 1.0}

    monkeypatch.setattr(sampler, "html", get_html)
    monkeypatch.setattr(sampler, "pdf", get_pdf)
    detail, _, reason = await sampler.detail({"detailUrl": "https://czzx.fudan.edu.cn/one.htm", "listTitle": "设备公告"})
    assert detail.content == "OCR extracted text"
    assert reason == "ocr_manual_review_required"


@pytest.mark.asyncio
async def test_agency_list_guid_must_match_the_public_frame():
    sampler = Sampler("agency")
    guid = "deabe3bd-a824-4422-9db8-5fcdc0218b17"
    frame = "https://eps.gdebidding.com/gdjd-xunjia/gonggaoxinxi/gongGao_view.html?guid=" + guid
    with pytest.raises(ValueError, match="list_and_frame_guid"):
        await sampler.agency_detail(
            frame, "/gdjd-xunjia/gonggaoxinxi/queryXiangMuByGuid.do?guid=", {"detailUrl": "https://eps.gdebidding.com/gg?guid=another"}, []
        )


def test_acceptance_bundle_preserves_hashes_and_keeps_body_outside_repo(tmp_path):
    inputs, bodies = tmp_path / "input", tmp_path / "bodies"
    inputs.mkdir()
    bodies.mkdir()
    (inputs / "summary.json").write_text(json.dumps({"fullContentDirectory": str(bodies)}))
    paths = []
    import hashlib

    for sid, profile in PROFILES.items():
        row = {
            "sourceId": sid,
            "discoveredUrl": profile.entry + "#test-detail",
            "title": "Test notice",
            "decision": "accepted",
            "contentMode": "html",
            "contentSha256": hashlib.sha256(b"Test body").hexdigest(),
        }
        (bodies / f"{sid}.jsonl").write_text(json.dumps({**row, "content": "Test body"}) + "\n")
        path = inputs / f"{sid}.json"
        path.write_text(
            json.dumps(
                {
                    "sourceId": sid,
                    "name": profile.name,
                    "samples": [row],
                    "listPages": [{}],
                    "summary": {"discoveredUniqueDetails": 1},
                    "requests": 2,
                }
            )
        )
        paths.append(path)
    output, private = tmp_path / "output", tmp_path / "private"
    summary = assemble(paths, [], output, private)
    assert summary["detailSamples"] == summary["accepted"] == 6
    assert summary["unattemptedDiscoveredDetails"] == 0
    assert all("content" not in row for row in map(json.loads, (output / "samples.jsonl").read_text().splitlines()))
    assert len((private / "records.jsonl").read_text().splitlines()) == 6
