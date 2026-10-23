"""Synthetic-only contracts for the observed university chtml detail family."""

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tender_sources.catalog_template_university import extract_detail  # noqa: E402

TITLE = "Laboratory equipment procurement announcement"
DATE_TEXT = "\u53d1\u5e03\u65e5\u671f\uff1a2026-10-22"
BODY = "The buyer invites suppliers to submit procurement tenders. " * 4
URL = "https://nkzbb.nankai.edu.cn/cghw/1234.chtml"
OBSERVED_PATHS = {
    "zhbb.cumt.edu.cn": ("zfcgyxgk", "cjgshwl", "xjgg"),
    "caigou.ucas.ac.cn": ("zfcghw", "zbcghw", "zbcgfw"),
    "cgzx.cpu.edu.cn": ("cjgshw", "zfcgyxgk", "zxcg", "cgxxhw"),
    "cgxx.ecnu.edu.cn": ("jggghw", "cggghw"),
    "czzx.ecust.edu.cn": ("pprojects", "pgoods", "pservices"),
    "cgzx.hust.edu.cn": ("ktgkjjcg", "cgjzcg"),
    "czzx.njau.edu.cn": ("fscggg", "pprojects", "\u653f\u5e9c\u91c7\u8d2d\u610f\u5411\u516c\u5f00"),
    "zbb.njau.edu.cn": ("hwgzgg", "rgoods", "rservices", "pgoods"),
    "zbb.nju.edu.cn": ("cjgshw",),
    "zb.nju.edu.cn": ("cgxxhw",),
    "nkzbb.nankai.edu.cn": ("yxgk", "jghw", "jgqt", "cghw", "cggc", "cgfw", "cgqt"),
    "ztb.xmu.edu.cn": ("jghw", "cghw", "cgfw"),
    "cgyztb.whut.edu.cn": ("cgfscg", "cgjzcg"),
    "cwcggl.swpu.edu.cn": ("jgtycg", "jgzzcg", "fzfcgyx", "cgtycg", "cgzzcg"),
    "cg.qdu.edu.cn": ("zbgghw", "jjjg", "cgxxhw"),
}


def html(title=TITLE, date=DATE_TEXT, body=BODY):
    return (
        '<div class="wrap"><div class="lright cright white">'
        f'<div class="ctitle"><h1>{title}</h1><div class="info">'
        f'<i>{date}</i><i>Views: 0</i><button>Print</button></div></div>'
        f'<div class="ccontent">{body}</div><div class="cattach"></div>'
        '<p class="cpage"><a href="index.chtml">Back</a></p></div></div>'
    )


def soup(markup):
    return BeautifulSoup(markup, "html.parser")


@pytest.mark.parametrize("host,section", [
    (host, section) for host, sections in OBSERVED_PATHS.items() for section in sections
])
def test_observed_host_and_column_paths_extract_only_detail_fields(host, section):
    document = soup(html())
    actual = extract_detail(document, f"https://{host}/{section}/1234.chtml")
    assert actual is not None
    assert actual[:2] == (TITLE, DATE_TEXT)
    assert actual[2] is document.select_one(".ccontent")
    assert "Back" not in actual[2].get_text()


def test_percent_encoded_observed_column_and_http_scheme_are_supported():
    document = soup(html())
    assert extract_detail(document, "http://czzx.njau.edu.cn/%E6%94%BF%E5%BA%9C%E9%87%87%E8%B4%AD%E6%84%8F%E5%90%91%E5%85%AC%E5%BC%80/1234.chtml")


@pytest.mark.parametrize("url", [
    "https://unknown.edu.cn/cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn.evil.example/cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn./cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn/cghw/index.chtml",
    "https://nkzbb.nankai.edu.cn/cghw/1234.html",
    "https://nkzbb.nankai.edu.cn/unknown/1234.chtml",
    "https://nkzbb.nankai.edu.cn/cghw/nested/1234.chtml",
    "https://nkzbb.nankai.edu.cn/cghw/../cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn/cghw%2F1234.chtml",
    "https://nkzbb.nankai.edu.cn/cghw/1234.chtml?redirect=1",
    "https://user@nkzbb.nankai.edu.cn/cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn:8443/cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn:bad/cghw/1234.chtml",
    "ftp://nkzbb.nankai.edu.cn/cghw/1234.chtml",
    "https://[malformed/cghw/1234.chtml",
    "https://nkzbb.nankai.edu.cn/cg%FF/1234.chtml",
    "https://cgzx.cpu.edu.cn/dyly/1234.chtml",
    "https://cg.xidian.edu.cn/hwcgjggs/1234.chtml",
    "https://cgzx.hust.edu.cn/fscgdownload/1234.chtml",
    "https://cgyztb.whut.edu.cn/center/1234.chtml",
    "https://caigou.ucas.ac.cn/zfcgfw/1234.chtml",
])
def test_unknown_or_unproven_scope_does_not_match(url):
    assert extract_detail(soup(html()), url) is None


@pytest.mark.parametrize("markup", [
    '<h1>Other template</h1><div class="ccontent">Body</div>',
    '<div class="wrap"><div class="ctitle"></div></div>',
    html().replace('class="ctitle"', 'class="article-title"'),
    html() + html(),
    html().replace('<h1>', '<h1>Repeated</h1><h1>', 1),
    html().replace('<div class="info">', '<div class="info"></div><div class="info">', 1),
    html().replace('<div class="ccontent">', '<div class="ccontent"></div><div class="ccontent">', 1),
    '<div class="wrap"><div class="ctitle"><h1>Title</h1></div>'
    '<div><div class="ccontent">Other record</div></div></div>',
])
def test_unknown_duplicate_or_mixed_record_structure_does_not_match(markup):
    assert extract_detail(soup(markup), URL) is None


@pytest.mark.parametrize("missing,field,expected", [
    (f"<h1>{TITLE}</h1>", 0, ""),
    (f"<i>{DATE_TEXT}</i>", 1, ""),
    (f'<div class="ccontent">{BODY}</div>', 2, None),
])
def test_missing_fields_are_not_fabricated_from_page_or_list(missing, field, expected):
    document = soup(
        html().replace(missing, "")
        + f'<footer><h1>{TITLE}</h1><i>{DATE_TEXT}</i><div class="ccontent">{BODY}</div></footer>'
    )
    actual = extract_detail(document, URL)
    assert actual is not None
    assert actual[field] == expected


def test_missing_info_does_not_borrow_date_from_current_time_or_body():
    document = soup(html(date="").replace('<div class="info">', '<div class="other-info">'))
    actual = extract_detail(document, URL)
    assert actual is not None
    assert actual[1] == ""


def test_swpu_metadata_order_and_project_dates_cannot_override_publication_date():
    metadata = (
        '<i>Budget: 100</i><i>Project date: 2026-01-01</i>'
        f'<i>{DATE_TEXT}</i><i>Views: 0</i><button>Print</button>'
    )
    markup = html().replace(f'<i>{DATE_TEXT}</i><i>Views: 0</i><button>Print</button>', metadata)
    actual = extract_detail(soup(markup), "http://cwcggl.swpu.edu.cn/jgtycg/1234.chtml")
    assert actual is not None
    assert actual[1] == DATE_TEXT


@pytest.mark.parametrize("date_markup", [
    '<i>Views: 2026-10-22</i>',
    f'<footer><i>{DATE_TEXT}</i></footer>',
    f'<i class="copyright">{DATE_TEXT}</i>',
    f'<i><span class="copyright">{DATE_TEXT}</span></i>',
    f'<i><nav>{DATE_TEXT}</nav></i>',
    f'<i><a href="index.chtml">{DATE_TEXT}</a></i>',
    f'<i>{DATE_TEXT}</i><i>{DATE_TEXT}</i>',
])
def test_metadata_date_ignores_chrome_links_and_ambiguous_fields(date_markup):
    actual = extract_detail(soup(html().replace(f'<i>{DATE_TEXT}</i>', date_markup)), URL)
    assert actual is not None
    assert actual[1] == ""


@pytest.mark.parametrize("wrapper", ["nav", "header", "footer"])
def test_page_chrome_cannot_supply_a_detail_frame(wrapper):
    assert extract_detail(soup(f"<{wrapper}>{html()}</{wrapper}>"), URL) is None


@pytest.mark.parametrize("identity", ["footer", "copyright", "navigation", "navbar"])
def test_class_or_id_chrome_cannot_supply_a_detail_frame(identity):
    assert extract_detail(soup(f'<div id="{identity}">{html()}</div>'), URL) is None


@pytest.mark.parametrize("body", [
    '<iframe src="/files/notice.pdf"></iframe>',
    '<object data="/files/notice.pdf"></object>',
    '<embed src="/files/notice.pdf">',
    '<nav><a href="other.chtml">Procurement notices</a></nav>',
    '<p><a href="other.chtml">View original</a></p>',
])
def test_embedded_navigation_and_pointer_bodies_are_preserved_for_shared_quality_gates(body):
    document = soup(html(body=body))
    actual = extract_detail(document, URL)
    assert actual is not None
    assert actual[2] is document.select_one(".ccontent")
    assert str(actual[2]) == str(soup(f'<div class="ccontent">{body}</div>').select_one(".ccontent"))


def test_extraction_does_not_mutate_source_document_or_normalize_invalid_dates():
    document = soup(html(date="\u53d1\u5e03\u65e5\u671f\uff1a2099-99-99"))
    before = str(document)
    actual = extract_detail(document, URL)
    assert actual is not None
    assert actual[1] == "\u53d1\u5e03\u65e5\u671f\uff1a2099-99-99"
    assert str(document) == before
