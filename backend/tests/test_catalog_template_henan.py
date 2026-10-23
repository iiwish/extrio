"""Synthetic-only contracts for the three scoped Henan transaction templates."""

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.tender_sources.catalog_template_henan import extract_detail, list_title  # noqa: E402

HOSTS = (
    "ggzyjyzx.neixiangxian.gov.cn",
    "ggzyjy.nanyang.gov.cn",
    "ggzyjyzx.zhenping.gov.cn",
)
GUID = "11111111-2222-4333-8444-555555555555"
TITLE = "Synthetic procurement notice"
DATE_TEXT = "\u53d1\u5e03\u65f6\u95f4\uff1a 2026-01-02 10:30"
PROSE = "The procurement project requires suppliers to provide a tender response. " * 4


def detail_url(host=HOSTS[0], category="002001/002001005"):
    return f"https://{host}/jyxx/{category}/20260102/{GUID}.html"


def html(*, title=TITLE, date_text=DATE_TEXT, body=None):
    body = f"<p>{PROSE}</p>" if body is None else body
    return f"""<html><body>
      <div class="container box"><div class="box-con">
        <div class="box-header">{title}</div>
        <div class="browse"><div class="browse-main">
          <span class="browse-item">\u6765\u6e90\uff1a</span>
          <span class="browse-item">{date_text}</span>
          <span class="browse-item">\u6d4f\u89c8\u6b21\u6570 11</span>
        </div></div>
        <div class="box-content"><div class="box-infor">
          <div id="infoContentM" class="box-article">{body}</div>
        </div></div>
      </div></div>
      <footer><span class="browse-item">\u53d1\u5e03\u65f6\u95f4\uff1a 2025-12-31</span></footer>
    </body></html>"""


def extract(markup=None, url=None):
    return extract_detail(BeautifulSoup(markup or html(), "html.parser"), url or detail_url())


@pytest.mark.parametrize("host", HOSTS)
def test_extracts_only_dedicated_transaction_fields(host):
    result = extract(url=detail_url(host))
    assert result is not None
    title, published, body = result
    assert title == TITLE
    assert published == DATE_TEXT
    assert body is not None
    assert body.get("id") == "infoContentM"
    assert body.get_text() == PROSE


@pytest.mark.parametrize(
    ("host", "category"),
    [
        (HOSTS[0], "002001/002001002"),
        (HOSTS[0], "002001/002001004"),
        (HOSTS[0], "002002/002002001"),
        (HOSTS[0], "002002/002002003"),
        (HOSTS[1], "002001/002001002"),
        (HOSTS[1], "002002/002002001"),
        (HOSTS[1], "002002/002002003"),
        (HOSTS[2], "002001/002001004"),
        (HOSTS[2], "002001/002001008"),
        (HOSTS[2], "002002/002002003"),
    ],
)
def test_accepts_each_saved_host_category(host, category):
    assert extract(url=detail_url(host, category)) is not None


@pytest.mark.parametrize(
    "url",
    [
        detail_url("ggzyjy.other.gov.cn"),
        detail_url("ggzyjy.nanyang.gov.cn.attacker.invalid"),
        detail_url("other.ggzyjy.nanyang.gov.cn"),
        detail_url("GGZYJY.NANYANG.GOV.CN."),
        detail_url().replace("https://", "ftp://"),
        detail_url().replace("https://", "https://user@"),
        detail_url().replace(".gov.cn/", ".gov.cn:8443/"),
        detail_url().replace("/jyxx/", "/news/"),
        detail_url().replace("/20260102/", "/202601/"),
        detail_url().replace(GUID, "not-a-uuid"),
        detail_url().replace(".html", ".pdf"),
        detail_url().replace(f"/20260102/{GUID}.html", "/transaction.html"),
        detail_url(category="002003/002003002"),
        detail_url(category="002002/002001005"),
        detail_url(HOSTS[1], "002001/002001004"),
        detail_url(HOSTS[2], "002002/002002001"),
    ],
)
def test_rejects_unproved_host_path_or_unsafe_url(url):
    assert extract(url=url) is None


def test_missing_title_does_not_use_document_title_or_body():
    markup = html(title="").replace("<html>", f"<html><title>{TITLE}</title>")
    result = extract(markup)
    assert result is not None
    assert result[0] == ""


def test_missing_publication_field_does_not_borrow_footer():
    result = extract(html(date_text=""))
    assert result is not None
    assert result[1] == ""


def test_other_dated_metadata_is_not_publication():
    result = extract(html(date_text="\u66f4\u65b0\u65f6\u95f4\uff1a 2026-01-02"))
    assert result is not None
    assert result[1] == ""


def test_nested_footer_date_is_not_publication():
    result = extract(html(date_text=f"<footer>{DATE_TEXT}</footer>"))
    assert result is not None
    assert result[1] == ""


def test_footer_class_date_is_not_publication():
    markup = html().replace('class="browse-item">' + DATE_TEXT, 'class="browse-item footer">' + DATE_TEXT)
    result = extract(markup)
    assert result is not None
    assert result[1] == ""


def test_nested_footer_class_date_is_not_publication():
    result = extract(html(date_text=f'<span class="copyright">{DATE_TEXT}</span>'))
    assert result is not None
    assert result[1] == ""


def test_title_inside_chrome_is_not_extracted():
    result = extract(html(title=f'<span class="navigation">{TITLE}</span>'))
    assert result is not None
    assert result[0] == ""


def test_multiple_publication_fields_are_ambiguous():
    markup = html().replace(DATE_TEXT, DATE_TEXT + f'</span><span class="browse-item">{DATE_TEXT}')
    result = extract(markup)
    assert result is not None
    assert result[1] == ""


def test_missing_body_does_not_fall_back_to_full_page():
    result = extract(html().replace('id="infoContentM"', 'id="unknownBody"'))
    assert result is not None
    assert result[2] is None


def test_other_content_id_without_proven_parent_is_not_body():
    result = extract(html().replace('class="box-infor"', 'class="other-layout"'))
    assert result is not None
    assert result[2] is None


@pytest.mark.parametrize("wrapper", ["nav", "header", "footer"])
def test_entire_template_inside_navigation_or_footer_is_unknown(wrapper):
    markup = html().replace('<div class="container box">', f'<{wrapper}><div class="container box">')
    markup = markup.replace("</body>", f"</{wrapper}></body>")
    assert extract(markup) is None


def test_unknown_layout_is_not_recognized():
    assert extract('<h1>Procurement notice</h1><article>2026-01-02</article>') is None


def test_duplicate_transaction_roots_are_unknown():
    assert extract(html() + html()) is None


@pytest.mark.parametrize(
    "body",
    [
        '<nav><a href="/">Procurement notice ' + PROSE + "</a></nav>",
        '<p>See original</p><iframe src="/notice.pdf"></iframe>',
        '<object data="/notice.pdf"></object>',
        '<embed src="/notice.pdf">',
    ],
)
def test_retains_navigation_and_embeds_for_shared_quality_rejection(body):
    soup = BeautifulSoup(html(body=body), "html.parser")
    result = extract_detail(soup, detail_url())
    assert result is not None
    assert result[2] is soup.select_one("#infoContentM")
    assert result[2].select_one("nav,iframe,object,embed") is not None


def test_future_date_is_not_corrected_or_borrowed_from_url():
    result = extract(html(date_text="\u53d1\u5e03\u65f6\u95f4\uff1a 2099-01-02"))
    assert result is not None
    assert result[1] == "\u53d1\u5e03\u65f6\u95f4\uff1a 2099-01-02"


def test_extraction_does_not_mutate_original_soup():
    soup = BeautifulSoup(html(), "html.parser")
    before = str(soup)
    assert extract_detail(soup, detail_url()) is not None
    assert str(soup) == before


def test_body_has_footer_layout_flag_does_not_mark_entire_article_as_footer():
    result = extract(html().replace("<body>", '<body class="has-footer">'))
    assert result is not None
    assert result[0] == TITLE
    assert result[1] == DATE_TEXT
    assert result[2] is not None


def list_html(title=TITLE):
    return f"""<html><body class="has-footer"><div class="container box">
      <div class="box-con public-box"><div class="public-con"><div class="box-content">
        <div id="info-list" class="public-list">
          <a class="public-list-item" href="/jyxx/002001/002001005/20260102/{GUID}.html">
            <div class="item-title text-overflow">{title}</div>
            <div class="item-date">2026-01-02</div>
          </a>
        </div>
      </div></div></div>
    </div></body></html>"""


@pytest.mark.parametrize(
    ("host", "paths"),
    [
        (HOSTS[0], ["002001/002001002", "002001/002001004", "002001/002001005",
                    "002002/002002001", "002002/002002003", "002003/002003002"]),
        (HOSTS[1], ["002001/002001002", "002001/002001004", "002001/002001005",
                    "002002/002002001", "002002/002002003", "002003/002003002"]),
        (HOSTS[2], ["002001/002001004", "002001/002001005", "002002",
                    "002002/002002001", "002002/002002003"]),
    ],
)
def test_list_title_supports_saved_list_paths_without_date_pollution(host, paths):
    soup = BeautifulSoup(list_html(), "html.parser")
    anchor = soup.select_one("a")
    paths = [f"/jyxx/{path}/transaction.html" for path in paths] + ["/jyxx/transactiontop.html"]
    for path in paths:
        assert list_title(anchor, f"https://{host}{path}") == TITLE


def test_list_title_does_not_strip_dates_that_belong_to_notice_title():
    title = "2026-01-02 procurement notice for 2026"
    anchor = BeautifulSoup(list_html(title), "html.parser").select_one("a")
    assert list_title(anchor, f"https://{HOSTS[0]}/jyxx/transactiontop.html") == title


@pytest.mark.parametrize(
    "url",
    [
        f"https://other.{HOSTS[0]}/jyxx/transactiontop.html",
        f"https://{HOSTS[0]}/news/transactiontop.html",
        f"https://{HOSTS[0]}/jyxx/002001/002001999/transaction.html",
        f"https://{HOSTS[2]}/jyxx/002001/002001002/transaction.html",
        f"https://{HOSTS[0]}/jyxx/transactiontop.html?page=2",
        detail_url(),
    ],
)
def test_list_title_unknown_scope_returns_none(url):
    anchor = BeautifulSoup(list_html(), "html.parser").select_one("a")
    assert list_title(anchor, url) is None


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('class="container box"', 'class="other-container"'),
        ('class="box-con public-box"', 'class="box-con"'),
        ('class="public-con"', 'class="other-con"'),
        ('class="box-content"', 'class="article-content"'),
        ('id="info-list"', 'id="other-list"'),
        ('class="public-list"', 'class="navigation"'),
        ('class="public-list-item"', 'class="other-item"'),
        ('href="/jyxx/', 'data-href="/jyxx/'),
    ],
)
def test_list_title_unknown_parent_or_anchor_structure_returns_none(old, new):
    anchor = BeautifulSoup(list_html().replace(old, new), "html.parser").select_one("a")
    assert list_title(anchor, f"https://{HOSTS[0]}/jyxx/transactiontop.html") is None


def test_list_title_missing_dedicated_title_never_returns_date():
    anchor = BeautifulSoup(list_html().replace('class="item-title text-overflow"', 'class="other"'), "html.parser").select_one("a")
    assert list_title(anchor, f"https://{HOSTS[0]}/jyxx/transactiontop.html") == ""


def test_list_title_footer_clone_is_not_a_notice():
    markup = list_html().replace('<div class="container box">', '<footer><div class="container box">')
    anchor = BeautifulSoup(markup, "html.parser").select_one("a")
    assert list_title(anchor, f"https://{HOSTS[0]}/jyxx/transactiontop.html") is None
