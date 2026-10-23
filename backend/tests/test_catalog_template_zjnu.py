"""Synthetic, offline contracts for the exact ZJNU detail template."""

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.catalog_template_zjnu import extract_detail  # noqa: E402

URL = "https://cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm"
TITLE = "Laboratory equipment procurement tender announcement"
DATE = "2026/10/21 11:53:49"
BODY = (
    "The procurement invites suppliers to submit tenders for laboratory equipment. "
    "Delivery, installation and acceptance testing are required for this tender. "
)


def page(title=TITLE, published=DATE, body=BODY):
    heading = f'<h1 class="arti-title">{title}</h1>' if title is not None else ""
    metadata = (
        '<p class="arti-metas"><span class="arti-update">Published '
        f'<span id="time">{published}</span></span></p>'
        if published is not None else ""
    )
    content = (
        '<div class="entry"><article class="read">'
        f'<div class="wp_articlecontent">{body}</div></article></div>'
        if body is not None else ""
    )
    return (
        '<div id="mainWraper"><div class="listMain"><div class="info-box">'
        f'<div class="article">{heading}{metadata}{content}</div>'
        '</div></div></div>'
    )


def extract(html, url=URL):
    return extract_detail(BeautifulSoup(html, "html.parser"), url)


@pytest.mark.parametrize("column", [20381, 20382, 20614, 20360, 20370, 20369])
def test_extracts_saved_column_template_with_raw_publication_text(column):
    result = extract(page(), URL.replace("c20381a", f"c{column}a"))
    assert result is not None
    title, published, body = result
    assert title == TITLE
    assert published == DATE
    assert body is not None and body.get("class") == ["wp_articlecontent"]
    assert body.get_text(" ", strip=True) == BODY.strip()


@pytest.mark.parametrize("field", ["title", "published", "body"])
def test_missing_field_stays_missing_without_document_fallback(field):
    values = {field: None}
    html = (
        f'<title>{TITLE}</title><meta name="PubDate" content="2026-10-21">'
        f'<article>{BODY}</article>' + page(**values)
    )
    result = extract(html)
    assert result is not None
    assert result[["title", "published", "body"].index(field)] == (None if field == "body" else "")


@pytest.mark.parametrize("url", [
    "https://example.org/2026/1021/c20381a591934/page.htm",
    "https://cgzx.zjnu.edu.cn.example.org/2026/1021/c20381a591934/page.htm",
    "https://www.cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm",
    "https://cgzx.zjnu.edu.cn./2026/1021/c20381a591934/page.htm",
    "https://user@cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm",
    "https://cgzx.zjnu.edu.cn:8443/2026/1021/c20381a591934/page.htm",
    "https://cgzx.zjnu.edu.cn:invalid/2026/1021/c20381a591934/page.htm",
    "ftp://cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm",
    "https://cgzx.zjnu.edu.cn/20381/list.htm",
    "https://cgzx.zjnu.edu.cn/2026/1021/c99999a591934/page.htm",
    "https://cgzx.zjnu.edu.cn/2026/1021/c20377a591934/page.htm",
    "https://cgzx.zjnu.edu.cn/2026/1021/c20441a591934/page.htm",
    "https://cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.html",
    "https://cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm/extra",
    "https://cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm?source=other",
    "https://cgzx.zjnu.edu.cn/2026/1021/c20381a591934/page.htm#other",
    "https://cgzx.zjnu.edu.cn/2026/1021/../c20381a591934/page.htm",
])
def test_unknown_or_unsafe_url_does_not_match(url):
    assert extract(page(), url) is None


def test_unknown_layout_does_not_match_by_site_or_body_class_alone():
    assert extract(f'<h1>{TITLE}</h1><div class="wp_articlecontent">{BODY}</div>') is None


def test_missing_date_does_not_borrow_footer_current_time_or_body_date():
    result = extract(
        '<footer><span id="time">2026/10/21 11:53:49</span></footer>'
        '<span class="arti-update">2099/01/01</span>'
        + page(published=None, body=BODY + " Published: 2026-10-21")
    )
    assert result is not None and result[1] == ""


@pytest.mark.parametrize("chrome", ["nav", "header", "footer"])
def test_template_inside_navigation_or_footer_is_not_a_detail(chrome):
    assert extract(f'<{chrome}>{page()}</{chrome}>') is None


@pytest.mark.parametrize("identity", ['id="footerWraper"', 'class="copyrights"', 'class="navigation"'])
def test_template_inside_classed_chrome_is_not_a_detail(identity):
    assert extract(f'<div {identity}>{page()}</div>') is None


def test_date_selector_must_be_in_direct_article_metadata():
    html = page(published=None).replace(
        '<div class="entry">',
        '<div class="entry"><p class="arti-metas"><span class="arti-update">'
        f'<span id="time">{DATE}</span></span></p>',
    )
    result = extract(html)
    assert result is not None and result[1] == ""


def test_footer_nested_in_metadata_cannot_supply_publication_date():
    html = page().replace(f'<span id="time">{DATE}</span>', f'<footer><span id="time">{DATE}</span></footer>')
    result = extract(html)
    assert result is not None and result[1] == ""


@pytest.mark.parametrize("identity", ["\u7248\u6743", "\u5bfc\u822a"])
@pytest.mark.parametrize("position", ["self", "descendant", "ancestor"])
def test_chinese_chrome_identity_cannot_supply_publication_date(identity, position):
    html = page()
    if position == "self":
        html = html.replace('<span id="time">', f'<span id="time" class="{identity}">')
    elif position == "descendant":
        html = html.replace(DATE, f'<span class="{identity}">{DATE}</span>')
    else:
        html = html.replace('class="arti-update"', f'class="arti-update {identity}"')
    result = extract(html)
    assert result is not None and result[1] == ""


@pytest.mark.parametrize("identity", ["\u7248\u6743", "\u5bfc\u822a"])
@pytest.mark.parametrize("position", ["self", "descendant"])
def test_chinese_chrome_identity_cannot_supply_title(identity, position):
    html = page()
    if position == "self":
        html = html.replace('class="arti-title"', f'class="arti-title {identity}"')
    else:
        html = html.replace(TITLE, f'<span class="{identity}">{TITLE}</span>')
    result = extract(html)
    assert result is not None and result[0] == ""


@pytest.mark.parametrize("identity", ["\u7248\u6743", "\u5bfc\u822a"])
@pytest.mark.parametrize("position", ["self", "ancestor"])
def test_chinese_chrome_identity_cannot_supply_body(identity, position):
    html = page()
    if position == "self":
        html = html.replace('class="wp_articlecontent"', f'class="wp_articlecontent {identity}"')
    else:
        html = html.replace('class="entry"', f'class="entry {identity}"')
    result = extract(html)
    assert result is not None and result[2] is None


def test_multiple_article_or_metadata_nodes_are_ambiguous():
    assert extract(page() + page()) is None
    duplicate = page().replace(
        '<span class="arti-update">Published ',
        '<span class="arti-update">Published <span id="time">2026/10/20</span>',
    )
    assert extract(duplicate) is None


def test_navigation_only_body_is_not_flattened_into_verified_prose():
    result = extract(page(body=f'<nav><a href="/20381/list.htm">{BODY}</a></nav>'))
    assert result is not None and result[2] is not None
    assert result[2].select_one("nav a") is not None


@pytest.mark.parametrize("embedding", [
    '<iframe src="/notice.pdf"></iframe>',
    '<object data="/notice.pdf"></object>',
    '<embed src="/notice.pdf">',
    '<iframe src="https://other.example/notice.htm"></iframe>',
])
def test_embedded_body_is_preserved_for_shared_rejection(embedding):
    result = extract(page(body=BODY + embedding))
    assert result is not None and result[2] is not None
    assert result[2].select_one("iframe,object,embed") is not None


def test_extraction_does_not_mutate_the_supplied_document():
    soup = BeautifulSoup(page(body=BODY + '<iframe src="/notice.pdf"></iframe>'), "html.parser")
    original = str(soup)
    assert extract_detail(soup, URL) is not None
    assert str(soup) == original
