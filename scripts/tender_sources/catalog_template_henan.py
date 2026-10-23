"""Scoped, offline field extraction for three Henan transaction templates."""

import re
from urllib.parse import SplitResult, urlsplit

from bs4 import BeautifulSoup, Tag

HOST_CATEGORIES = {
    "ggzyjyzx.neixiangxian.gov.cn": frozenset({
        "002001/002001002", "002001/002001004", "002001/002001005",
        "002002/002002001", "002002/002002003",
    }),
    "ggzyjy.nanyang.gov.cn": frozenset({
        "002001/002001002", "002001/002001005", "002002/002002001", "002002/002002003",
    }),
    "ggzyjyzx.zhenping.gov.cn": frozenset({
        "002001/002001004", "002001/002001005", "002001/002001008", "002002/002002003",
    }),
}
HOST_LIST_CATEGORIES = {
    "ggzyjyzx.neixiangxian.gov.cn": frozenset({
        "002001/002001002", "002001/002001004", "002001/002001005",
        "002002/002002001", "002002/002002003", "002003/002003002",
    }),
    "ggzyjy.nanyang.gov.cn": frozenset({
        "002001/002001002", "002001/002001004", "002001/002001005",
        "002002/002002001", "002002/002002003", "002003/002003002",
    }),
    "ggzyjyzx.zhenping.gov.cn": frozenset({
        "002001/002001004", "002001/002001005", "002002", "002002/002002001", "002002/002002003",
    }),
}
DETAIL_PATH = re.compile(
    r"/jyxx/(?P<category>00200[12]/00200[12]\d{3})/\d{8}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.html"
)
PUBLICATION_LABEL = re.compile(r"^\u53d1\u5e03\u65f6\u95f4\s*[:\uff1a]")
CHROME_IDENTITY = re.compile(r"foot|copyright|navigation|navbar|\u7248\u6743|\u5bfc\u822a", re.IGNORECASE)


def _chrome(node: Tag) -> bool:
    for current in [node, *node.parents]:
        if not isinstance(current, Tag):
            continue
        if current.name in {"nav", "header", "footer"}:
            return True
        if current.name in {"body", "html", "[document]"}:
            continue
        identity = str(current.get("id", "")) + " " + " ".join(current.get("class", []))
        if CHROME_IDENTITY.search(identity):
            return True
    return False


def _one(parent: Tag, selector: str) -> Tag | None:
    found = parent.select(selector)
    return found[0] if len(found) == 1 and not _chrome(found[0]) else None


def _field_text(node: Tag | None) -> str:
    if node is None or node.select_one("script,style,noscript,template,nav,header,footer,form"):
        return ""
    if any(_chrome(child) for child in node.find_all(True)):
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _scoped_url(url: str) -> SplitResult | None:
    if re.search(r"[\x00-\x20\x7f\\]", url):
        return None
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or parts.hostname not in HOST_CATEGORIES
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 80, 443}
            or parts.query
            or parts.fragment
        ):
            return None
    except ValueError:
        return None
    return parts


def extract_detail(soup: BeautifulSoup, url: str) -> tuple[str, str, Tag | None] | None:
    parts = _scoped_url(url)
    if parts is None:
        return None
    path = DETAIL_PATH.fullmatch(parts.path)
    if path is None or path["category"] not in HOST_CATEGORIES[parts.hostname]:
        return None
    roots = soup.select(".container.box > .box-con")
    if len(roots) != 1 or _chrome(roots[0]):
        return None
    root = roots[0]
    if _one(root, ":scope > .box-content") is None:
        return None
    title = _field_text(_one(root, ":scope > .box-header"))
    clocks = []
    browse = _one(root, ":scope > .browse > .browse-main")
    if browse is not None:
        for item in browse.select(":scope > .browse-item"):
            text = _field_text(item) if not _chrome(item) else ""
            if PUBLICATION_LABEL.match(text):
                clocks.append(text)
    published = clocks[0] if len(clocks) == 1 else ""
    # Preserve the original body, including embeds, for the shared quality gate.
    body = _one(root, ":scope > .box-content > .box-infor > #infoContentM.box-article")
    return title, published, body


def list_title(anchor: Tag, url: str) -> str | None:
    """Extract the list field without its separate date; url is the list URL."""
    parts = _scoped_url(url)
    if parts is None:
        return None
    paths = {f"/jyxx/{category}/transaction.html" for category in HOST_LIST_CATEGORIES[parts.hostname]}
    if parts.path not in paths | {"/jyxx/transactiontop.html"}:
        return None
    if anchor.name != "a" or "public-list-item" not in anchor.get("class", []) or not anchor.get("href"):
        return None
    chain = (
        ("info-list", {"public-list"}),
        (None, {"box-content"}),
        (None, {"public-con"}),
        (None, {"box-con", "public-box"}),
        (None, {"container", "box"}),
    )
    parent = anchor.parent
    for identity, classes in chain:
        if (
            not isinstance(parent, Tag)
            or parent.name != "div"
            or (identity is not None and parent.get("id") != identity)
            or not classes.issubset(parent.get("class", []))
        ):
            return None
        parent = parent.parent
    if _chrome(anchor):
        return None
    return _field_text(_one(anchor, ":scope > .item-title"))
