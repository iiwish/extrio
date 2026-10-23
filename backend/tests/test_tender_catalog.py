"""Offline contracts for CSV accounting and conservative notice inspection."""

import csv
import io
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.catalog import (  # noqa: E402
    CatalogEntry,
    DetailCandidate,
    historical_restriction,
    inspect_detail,
    inspect_list,
    load_catalog,
    validate_entry,
)

LIST_URL = "https://example.org/procurement/list.html"
TITLE = "Laboratory equipment procurement tender announcement"
BODY = (
    "The buyer invites qualified suppliers to submit tenders for laboratory equipment. "
    "The procurement includes installation, delivery and acceptance testing. "
    "Tender documents are available during the published period. "
)


def entry(url=LIST_URL, **metadata):
    return CatalogEntry("main:2:fixture", "main", 2, url, "Fixture", metadata)


def candidate(**values):
    return DetailCandidate(
        values.get("url", "https://example.org/procurement/notice-123.html"),
        values.get("title", TITLE),
        values.get("published_at", "2026-10-22"),
        values.get("basis", "static_notice_link+row_date"),
    )


def list_html(title=TITLE, target="notice-123.html", date="2026-10-22"):
    return f'<title>Procurement notices</title><ul><li><a href="{target}">{title}</a><time>{date}</time></li></ul>'


def detail_html(title=TITLE, date="2026-10-22", body=BODY):
    return (
        f'<title>{title}</title><article><h1>{title}</h1><time datetime="{date}"></time>'
        f'<div class="notice-content">{body}</div></article>'
    )


def test_catalog_bom_quotes_duplicates_empty_url_and_blank_lines_are_accounted(tmp_path):
    rows = io.StringIO(newline="")
    writer = csv.writer(rows)
    writer.writerow(["entryUrl", "name", "sourceId", "checkedOn", "notes"])
    writer.writerow([LIST_URL, 'Buyer, "Laboratory"', "TS-1", "2026-10-16", "line one\nline two"])
    writer.writerow([LIST_URL, "Duplicate", "TS-2", "2026-10-16", ""])
    writer.writerow(["", "Missing URL", "TS-3", "2026-10-16", ""])
    writer.writerow([])
    path = tmp_path / "catalog.csv"
    path.write_text(rows.getvalue(), encoding="utf-8-sig")
    actual = load_catalog(path, "main")
    assert len(actual) == 3
    assert actual[0].name == 'Buyer, "Laboratory"'
    assert actual[0].metadata["notes"] == "line one\nline two"
    assert actual[0].metadata["sourceId"] == "TS-1"
    assert actual[0].metadata["checkedOn"] == "2026-10-16"
    assert actual[0].entry_url == actual[1].entry_url == LIST_URL
    assert len({row.entry_id for row in actual}) == 3
    assert actual[2].entry_url == ""
    assert actual == load_catalog(path, "main")
    assert actual[0].entry_id != load_catalog(path, "review")[0].entry_id
    assert asdict(actual[0])["group"] == "main"


def test_catalog_reports_physical_start_line_even_with_multiline_fields(tmp_path):
    path = tmp_path / "catalog.csv"
    path.write_text('entryUrl,name\nhttps://example.org/a,"first\nsecond"\n\nhttps://example.org/b,last\n')
    assert [row.row_number for row in load_catalog(path, "main")] == [2, 5]


def test_catalog_rejects_missing_or_duplicate_required_column(tmp_path):
    path = tmp_path / "catalog.csv"
    for text in ["url,name\nhttps://example.org,a\n", "entryUrl,entryUrl\na,b\n", ""]:
        path.write_text(text)
        with pytest.raises(ValueError, match="entryUrl"):
            load_catalog(path, "main")


@pytest.mark.parametrize("url", [
    "", "file:///etc/passwd", "javascript:alert(1)", "ftp://example.org/a",
    "https://user@example.org/a", "https://user:password@example.org/a", "https://example.org:8443/a",
    "http://localhost/a", "https://LOCALHOST./a", "http://thing.localhost/a", "http://127.0.0.1/a",
    "http://10.1.2.3/a", "https://192.168.1.1/a", "http://169.254.169.254/a", "https://[::1]/a",
    "http://[fc00::1]/a", "http://[::ffff:127.0.0.1]/a", "https://example.org:notaport/a",
    "https://[malformed/a", "https://example.org/\nnotice", "https://example.org\\@127.0.0.1/a",
])
def test_validate_entry_rejects_unsafe_urls(url):
    assert validate_entry(entry(url))


@pytest.mark.parametrize("url", [LIST_URL, "http://example.org:80/a?q=1", "https://example.org:443/a", "https://93.184.216.34/a"])
def test_validate_entry_keeps_public_urls_for_network_dns_recheck(url):
    assert validate_entry(entry(url)) is None


def test_historical_restriction_only_explicit_evidence_and_preserves_provenance():
    restricted = entry(loginRequired="\u662f", checkedOn="2026-10-16", loginEvidence="\u5217\u8868\u663e\u793a\u8bf7\u5148\u767b\u5f55")
    reason = historical_restriction(restricted)
    assert "2026-10-16" in reason and "loginRequired" in reason
    assert historical_restriction(entry(httpStatus="403", checkedOn="2026-10-16"))
    assert historical_restriction(entry(verificationStatus="\u660e\u786e\u9700\u767b\u5f55", checkedOn="2026-10-16"))


@pytest.mark.parametrize("metadata", [
    {"loginRequired": "\u5f85\u6838\u9a8c", "loginEvidence": "\u4e0d\u53ef\u8fbe/JS\u5916\u58f3\u4e0d\u7b49\u4e8e\u9700\u8981\u767b\u5f55"},
    {"httpStatus": "200", "renderType": "JS/\u52a8\u6001\u52a0\u8f7d\u5f85\u6838\u9a8c"},
    {"httpStatus": "", "verificationStatus": "TLS connection failed"},
    {"detailLoginRequired": "\u662f", "attachmentLoginRequired": "\u662f", "loginRequired": "\u5426"},
])
def test_historical_unknown_or_detail_only_restriction_does_not_skip_list(metadata):
    assert historical_restriction(entry(**metadata)) is None


def test_static_list_requires_notice_semantics_local_date_and_real_href():
    inspection = inspect_list(list_html(), LIST_URL)
    assert inspection.status == "candidate_list"
    assert len(inspection.candidates) == 1
    item = inspection.candidates[0]
    assert item.url == "https://example.org/procurement/notice-123.html"
    assert item.title == TITLE and item.published_at == "2026-10-22"
    assert "date" in item.basis
    assert asdict(inspection)["candidates"][0]["title"] == TITLE


@pytest.mark.parametrize("html", [
    '<title>University home</title><nav><a href="/notice">Procurement tender announcement</a></nav><footer>2026-10-22</footer>',
    '<title>Procurement</title><script>window.records=[{"title":"Tender announcement","url":"/notice"}]</script><div id="app"></div>',
    '<title>News</title><ul><li><a href="/news/1">University news and annual meeting</a><time>2026-10-22</time></li></ul>',
    '<title>Procurement</title><li><a href="javascript:show(1)">Procurement tender announcement</a>2026-10-22</li>',
    '<title>Procurement</title><li><a href="/notice.pdf">Procurement tender announcement</a>2026-10-22</li>',
    '<title>Procurement</title><li><a href="/notice">Procurement tender announcement</a>2026-99-99</li>',
    '<title>Procurement</title><li><a href="/notice">Procurement tender announcement</a></li><footer>2026-10-22</footer>',
])
def test_list_does_not_turn_navigation_scripts_news_pdf_or_missing_dates_into_candidates(html):
    result = inspect_list(html, LIST_URL)
    assert result.status == "needs_adapter" and not result.candidates


@pytest.mark.parametrize("html", [
    '<title>Login required</title><form><input type="password"></form>',
    '<title>Access denied</title><p>You do not have permission to view this page.</p>',
    '<title>Security check</title><p>Please complete the CAPTCHA to continue.</p>',
    '<title>\u8bbf\u95ee\u8fc7\u4e8e\u9891\u7e41</title><p>\u8bf7\u7a0d\u540e\u518d\u8bd5</p>',
])
def test_html_login_access_and_challenge_pages_are_restricted(html):
    assert inspect_list(html, LIST_URL).status == "restricted"
    assert inspect_detail(html, candidate().url, candidate())["status"] == "restricted"


def test_cross_host_candidate_is_diagnostic_only_not_followable():
    result = inspect_list(list_html(target="https://other.example/notice-123.html"), LIST_URL)
    assert result.status == "needs_adapter"
    assert result.reason == "cross_host_notice_links"
    assert not result.candidates


def test_list_deduplicates_href_and_ignores_html_base_override():
    html = '<base href="https://evil.example/">' + list_html() + list_html()
    result = inspect_list(html, LIST_URL)
    assert len(result.candidates) == 1
    assert result.candidates[0].url.startswith("https://example.org/")


def test_detail_has_bound_title_explicit_publication_date_and_article_body():
    result = inspect_detail(detail_html(), candidate().url, candidate())
    assert result["status"] == "sample_readable"
    assert result["contentMode"] == "html_candidate"
    assert result["title"] == TITLE and result["publishedAt"] == "2026-10-22"
    assert result["content"] == BODY.strip()
    assert result["reason"] == "static_candidate_not_signed_rule"


@pytest.mark.parametrize(("html", "reason"), [
    (detail_html(title="Different procurement tender announcement"), "title_mismatch"),
    (detail_html(date="2026-10-21"), "publication_date_mismatch"),
    (detail_html(date=""), "missing_publication_date"),
    (detail_html(body="Short notice"), "body_too_short"),
    (detail_html(body='<a href="original.html">\u8be6\u89c1\u539f\u6587</a>'), "original_pointer"),
    (detail_html(body='<iframe src="notice.pdf"></iframe>'), "pdf_requires_adapter"),
    (detail_html(body='<nav>' + BODY + '</nav>'), "missing_notice_body"),
])
def test_detail_incomplete_or_identity_mismatch_never_passes(html, reason):
    result = inspect_detail(html, candidate().url, candidate())
    assert result["status"] in {"needs_adapter", "body_incomplete"}
    assert result["reason"] == reason


def test_detail_never_borrows_footer_date_or_whole_homepage_as_notice_body():
    html = f'<title>{TITLE}</title><h1>{TITLE}</h1><main>{BODY}</main><footer>2026-10-22</footer>'
    result = inspect_detail(html, candidate().url, candidate())
    assert result["status"] != "sample_readable"
    assert not result["publishedAt"]


def test_detail_rejects_pure_link_navigation_despite_notice_container_name():
    links = "".join(f'<li><a href="category-{index}">{TITLE} category {index}</a></li>' for index in range(8))
    result = inspect_detail(detail_html(body=f"<ul>{links}</ul>"), candidate().url, candidate())
    assert result["status"] == "body_incomplete" and result["reason"] == "navigation_or_link_only_body"


@pytest.mark.parametrize("node", [
    '<footer class="date">2026-10-22</footer>',
    '<nav class="time">2026-10-22</nav>',
    '<header itemprop="datePublished">2026-10-22</header>',
])
def test_date_container_itself_cannot_be_footer_navigation_or_header(node):
    html = f'<h1>{TITLE}</h1><div class="notice-content">{BODY}</div>{node}'
    result = inspect_detail(html, candidate().url, candidate())
    assert result["status"] == "needs_adapter" and result["reason"] == "missing_publication_date"
    assert not result["publishedAt"]


def test_generic_date_class_copyright_is_not_publication_metadata():
    html = f'<h1>{TITLE}</h1><div class="notice-content">{BODY}</div><div class="date">Copyright 2026-10-22</div>'
    result = inspect_detail(html, candidate().url, candidate())
    assert result["status"] == "needs_adapter" and result["reason"] == "missing_publication_date"


@pytest.mark.parametrize("target", [
    "https://user@example.org/procurement/a", "https://example.org:8443/procurement/a",
    "http://example.org/procurement/a", "https://127.0.0.1/procurement/a",
])
def test_list_never_emits_unsafe_or_downgrade_detail_targets(target):
    result = inspect_list(list_html(target=target), LIST_URL)
    assert not result.candidates and result.status == "needs_adapter"


def test_uppercase_pdf_frame_is_explicitly_classified_without_following_it():
    result = inspect_detail(detail_html(body='<iframe src="notice.PDF"></iframe>'), candidate().url, candidate())
    assert result["reason"] == "pdf_requires_adapter"


def test_future_publication_date_is_not_current_notice_evidence():
    result = inspect_list(list_html(date="2099-10-22"), LIST_URL)
    assert result.status == "needs_adapter" and not result.candidates
    result = inspect_detail(detail_html(date="2099-10-22"), candidate().url, candidate(published_at="2099-10-22"))
    assert result["status"] == "needs_adapter" and result["reason"] == "missing_publication_date"


@pytest.mark.parametrize("markup", [
    '<div class="footer"><span class="publication-date">2026-10-22</span></div>',
    '<div id="footInfo"><span class="article-date">2026-10-22</span></div>',
    '<div class="copyright"><span>Published on: 2026-10-22</span></div>',
    '<div class="footer publication-date">2026-10-22</div>',
    '<div class="navigation"><span class="publish-time">2026-10-22</span></div>',
])
def test_publication_metadata_in_chrome_classes_or_ids_does_not_supply_date(markup):
    html = f'<h1>{TITLE}</h1><div class="notice-content">{BODY}</div>{markup}'
    result = inspect_detail(html, candidate().url, candidate())
    assert result["status"] == "needs_adapter" and result["reason"] == "missing_publication_date"


def test_notice_semantics_include_correct_chinese_selection_terms():
    for title in [
        "\u8bbe\u5907\u7ef4\u62a4\u670d\u52a1\u9048\u9009\u516c\u544a",
        "\u8bbe\u5907\u7ef4\u62a4\u670d\u52a1\u5019\u9009\u4eba\u516c\u793a",
    ]:
        assert inspect_list(list_html(title=title), LIST_URL).status == "candidate_list"


def test_detail_does_not_accept_long_generic_website_help_as_notice_body():
    body = "The website provides links and general information. Please use the navigation to locate services. " * 4
    result = inspect_detail(detail_html(body=body), candidate().url, candidate())
    assert result["status"] != "sample_readable" and result["reason"] == "notice_body_semantics_unverified"


def test_detail_title_comparison_uses_existing_normalization():
    result = inspect_detail(detail_html(title=TITLE.upper()), candidate().url, candidate())
    assert result["status"] == "sample_readable"


def test_detail_rejects_candidate_url_substitution_and_garbled_text():
    assert inspect_detail(detail_html(), "https://example.org/other.html", candidate())["reason"] == "candidate_url_mismatch"
    result = inspect_detail(detail_html(body="\ufffd" * 200), candidate().url, candidate())
    assert result["status"] == "body_incomplete" and result["reason"] == "garbled_text"


def test_verified_profile_list_and_detail_remain_bound_to_same_notice():
    url = "http://www.ccgp.gov.cn/cggg/zygg/"
    title = "\u8bbe\u5907\u91c7\u8d2d\u516c\u5f00\u62db\u6807\u516c\u544a"
    html = f'<ul class="c_list_bid"><li><a title="{title}" href="gkzb/202610/test.htm">{title}</a><em>2026-10-22</em></li></ul>'
    result = inspect_list(html, url)
    assert result.status == "candidate_list" and len(result.candidates) == 1
    item = result.candidates[0]
    detail = f'<h2 class="tc">{title}</h2><span id="pubTime">2026-10-22</span><div class="vF_detail_content">{BODY}</div>'
    parsed = inspect_detail(detail, item.url, item)
    assert parsed["status"] == "sample_readable" and parsed["contentMode"] == "html_profile"
