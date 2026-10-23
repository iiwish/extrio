"""Extract the observed university chtml family without deciding body quality."""

import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag

OBSERVED_COLUMNS = {
    "zhbb.cumt.edu.cn": frozenset({"zfcgyxgk", "cjgshwl", "xjgg"}),
    "caigou.ucas.ac.cn": frozenset({"zfcghw", "zbcghw", "zbcgfw"}),
    "cgzx.cpu.edu.cn": frozenset({"cjgshw", "zfcgyxgk", "zxcg", "cgxxhw"}),
    "cgxx.ecnu.edu.cn": frozenset({"jggghw", "cggghw"}),
    "czzx.ecust.edu.cn": frozenset({"pprojects", "pgoods", "pservices"}),
    "cgzx.hust.edu.cn": frozenset({"ktgkjjcg", "cgjzcg"}),
    "czzx.njau.edu.cn": frozenset({"fscggg", "pprojects", "\u653f\u5e9c\u91c7\u8d2d\u610f\u5411\u516c\u5f00"}),
    "zbb.njau.edu.cn": frozenset({"hwgzgg", "rgoods", "rservices", "pgoods"}),
    "zbb.nju.edu.cn": frozenset({"cjgshw"}),
    "zb.nju.edu.cn": frozenset({"cgxxhw"}),
    "nkzbb.nankai.edu.cn": frozenset({"yxgk", "jghw", "jgqt", "cghw", "cggc", "cgfw", "cgqt"}),
    "ztb.xmu.edu.cn": frozenset({"jghw", "cghw", "cgfw"}),
    "cgyztb.whut.edu.cn": frozenset({"cgfscg", "cgjzcg"}),
    "cwcggl.swpu.edu.cn": frozenset({"jgtycg", "jgzzcg", "fzfcgyx", "cgtycg", "cgzzcg"}),
    "cg.qdu.edu.cn": frozenset({"zbgghw", "jjjg", "cgxxhw"}),
}
_CHROME = re.compile(r"foot|copyright|navigation|navbar|\u7248\u6743|\u5bfc\u822a", re.IGNORECASE)
_PUBLICATION_LABEL = re.compile(r"^\u53d1\u5e03\u65e5\u671f\s*[:\uff1a]")


def _in_chrome(node: Tag) -> bool:
    for current in (node, *node.parents):
        if not isinstance(current, Tag):
            continue
        if current.name in {"nav", "header", "footer"}:
            return True
        identity = str(current.get("id", "")) + " " + " ".join(current.get("class", []))
        if _CHROME.search(identity):
            return True
    return False


def _has_chrome(node: Tag) -> bool:
    return _in_chrome(node) or any(_in_chrome(child) for child in node.find_all(True))


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _known_url(url: str) -> bool:
    if re.search(r"[\x00-\x20\x7f\\]", url):
        return False
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or parts.hostname not in OBSERVED_COLUMNS
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 80, 443}
            or parts.query
            or re.search(r"%(?:2f|5c|00)", parts.path, re.IGNORECASE)
        ):
            return False
        path = unquote(parts.path, errors="strict")
        match = re.fullmatch(r"/([^/]+)/[1-9]\d*\.chtml", path)
        return bool(match and match.group(1) in OBSERVED_COLUMNS[parts.hostname])
    except (ValueError, UnicodeError):
        return False


def extract_detail(soup: BeautifulSoup, url: str) -> tuple[str, str, Tag | None] | None:
    """Return raw fields only for evidenced host/column and the shared DOM frame."""
    if not _known_url(url):
        return None
    frames = [node for node in soup.select("div.ctitle") if not _in_chrome(node)]
    if len(frames) != 1:
        return None
    frame = frames[0]
    parent = frame.parent
    if not isinstance(parent, Tag) or parent.name != "div" or not frame.find_parent("div", class_="wrap"):
        return None
    titles = frame.select(":scope > h1")
    infos = frame.select(":scope > div.info")
    bodies = [node for node in soup.select("div.ccontent") if not _in_chrome(node)]
    if not titles and not infos and not bodies:
        return None
    if len(titles) > 1 or len(infos) > 1 or len(bodies) > 1 or (bodies and bodies[0].parent is not parent):
        return None
    title = _text(titles[0]) if titles and not _has_chrome(titles[0]) else ""
    dates = []
    if infos and not _in_chrome(infos[0]):
        # The 94 matching saved pages place publication metadata in a direct i.
        for node in infos[0].select(":scope > i"):
            if _has_chrome(node) or node.select_one("a,button,form"):
                continue
            raw = _text(node)
            if _PUBLICATION_LABEL.match(raw):
                dates.append(raw)
    return title, dates[0] if len(dates) == 1 else "", bodies[0] if bodies else None
