import pytest

from extrio.harvest import discover_records_from_spec


def next_url(anchor):
    spec = {"itemsSelector": "css:li", "fields": {}, "pagination": {"type": "next_link", "selector": "css:a"}}
    return discover_records_from_spec(anchor, "https://example.com/list/index.html", spec)[1]


@pytest.mark.parametrize(
    "script", ["location.href=encodeURI('index_2.html');", "window.location.href = 'index_2.html'", 'location.href="index_2.html";']
)
def test_static_navigation_resolves_without_executing_script(script):
    from html import escape

    assert next_url(f'<a href="###" onclick="{escape(script, quote=True)}">Next</a>') == "https://example.com/list/index_2.html"


@pytest.mark.parametrize(
    "script",
    [
        "location.href=url",
        "location.href='index_'+page+'.html'",
        "location.href='index_2.html';steal()",
        "location.href=encodeURI('https://evil.test/next')",
        "location.href='javascript:alert(1)'",
        "location.href='//evil.test/next'",
        "location.href='index.html'",
        "location.href='\\x69ndex_2.html'",
    ],
)
def test_dynamic_or_unsafe_navigation_is_not_a_next_url(script):
    from html import escape

    assert next_url(f'<a href="###" onclick="{escape(script, quote=True)}">Next</a>') is None


def test_regular_href_still_works_and_fragment_only_is_not_pagination():
    assert next_url('<a href="index_2.html">Next</a>') == "https://example.com/list/index_2.html"
    assert next_url('<a href="#next">Next</a>') is None


@pytest.mark.parametrize(
    "pagination,code",
    [
        ({"type": "none"}, "PAGINATION_OMITTED"),
        ({"type": "page"}, "PAGINATION_MODE_MISMATCH"),
        ({"type": "next_link", "selector": "css:a.next"}, "PAGINATION_NEXT_LINK_MISSING"),
    ],
)
def test_discovery_rejects_wrong_or_disabled_pagination_with_actionable_hints(pagination, code):
    from extrio.explorer import _pagination_issues

    plan = {"mode": "list_detail", "list": {"itemsSelector": "css:li", "fields": {}, "pagination": pagination}}
    html = '<a href="###" onclick="location.href=encodeURI(\'index_2.html\');">下一页</a>'
    issue = _pagination_issues(plan, html, "https://example.com/index.html")[0]
    assert issue["code"] == code
    assert issue["field"] == "list.pagination"
    assert issue["navigationCandidates"][0]["targetUrl"] == "https://example.com/index_2.html"
