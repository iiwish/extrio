"""Narrow extraction for the saved ZJNU procurement detail template."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

DETAIL_PATH = re.compile(
    r"/(?:19|20)\d{2}/\d{4}/c(?:20381|20382|20614|20360|20370|20369)a\d+/page\.htm"
)
ARTICLE_SELECTOR = "#mainWraper .listMain .info-box > div.article"
TITLE_SELECTOR = ":scope > h1.arti-title"
DATE_SELECTOR = ":scope > p.arti-metas > span.arti-update > span#time"
BODY_SELECTOR = ":scope > div.entry > article.read > div.wp_articlecontent"


def _in_chrome(node: Tag) -> bool:
    for current in [node, *node.parents]:
        if not isinstance(current, Tag):
            continue
        if current.name in {"nav", "header", "footer"}:
            return True
        identity = str(current.get("id", "")) + " " + " ".join(current.get("class", []))
        if re.search(r"foot|copyright|navigation|navbar|\u7248\u6743|\u5bfc\u822a", identity, re.IGNORECASE):
            return True
    return False


def _field_text(node: Tag | None) -> str:
    if node is None or _in_chrome(node) or any(_in_chrome(child) for child in node.find_all(True)):
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def extract_detail(soup: BeautifulSoup, url: str) -> tuple[str, str, Tag | None] | None:
    if re.search(r"[\x00-\x20\x7f\\]", url):
        return None
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or parts.hostname != "cgzx.zjnu.edu.cn"
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 80, 443}
            or parts.query
            or parts.fragment
            or not DETAIL_PATH.fullmatch(parts.path)
        ):
            return None
    except ValueError:
        return None

    articles = soup.select(ARTICLE_SELECTOR)
    if len(articles) != 1 or _in_chrome(articles[0]):
        return None
    article = articles[0]
    fields = [article.select(selector) for selector in (TITLE_SELECTOR, DATE_SELECTOR, BODY_SELECTOR)]
    if any(len(nodes) > 1 for nodes in fields):
        return None
    title, published, body = [nodes[0] if nodes else None for nodes in fields]
    # Keep the body DOM intact so the shared quality gate can reject embedded or navigation-only content.
    return _field_text(title), _field_text(published), body if body is not None and not _in_chrome(body) else None
