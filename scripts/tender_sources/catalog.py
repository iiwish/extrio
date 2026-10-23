"""CSV accounting and conservative, offline inspection for catalog sampling."""

import csv
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from extrio.harvest import titles_consistent

from .adapters import PROFILES, parse_detail, parse_list, validate_detail
from .catalog_template_henan import extract_detail as henan_detail
from .catalog_template_henan import list_title as henan_list_title
from .catalog_template_university import extract_detail as university_detail
from .catalog_template_zjnu import extract_detail as zjnu_detail

NOTICE = re.compile(
    r"\u62db\u6807|\u91c7\u8d2d|\u4e2d\u6807|\u6210\u4ea4|\u8be2\u4ef7|\u7ade\u4e89\u6027|\u78cb\u5546|\u9048\u9009|"
    r"\u6bd4\u9009|\u7ade\u4ef7|\u62db\u79df|\u62cd\u5356|\u5f81\u96c6|\u5019\u9009\u4eba|\u53d8\u66f4\u516c\u544a|\u66f4\u6b63\u516c\u544a|"
    r"\btender\b|\bprocurement\b|\bbid(?:ding)?\b|\bcontract award\b",
    re.IGNORECASE,
)
BODY_NOTICE = re.compile(
    r"\u91c7\u8d2d|\u6295\u6807|\u62db\u6807|\u4e2d\u6807|\u6210\u4ea4|\u4f9b\u5e94\u5546|\u9879\u76ee\u7f16\u53f7|"
    r"\u54cd\u5e94\u6587\u4ef6|\u5f00\u6807|\u9884\u7b97|\u62a5\u4ef7|\u78cb\u5546|\u6bd4\u9009|"
    r"\btender|\bprocurement\b|\bsuppliers?\b|\bbid(?:s|der|ding)?\b|\bcontract award\b",
    re.IGNORECASE,
)
ASSET = re.compile(
    r"\.(?:pdf|docx?|xlsx?|zip|rar|7z|jpe?g|png|gif)(?:[?#]|$)", re.IGNORECASE
)
SKIP_LINK = re.compile(
    r"^(?:\u9996\u9875|\u4e0a\u4e00\u9875|\u4e0b\u4e00\u9875|\u5c3e\u9875|\u66f4\u591a|"
    r"\u91c7\u8d2d\u516c\u544a|\u62db\u6807\u516c\u544a|\u4e2d\u6807\u516c\u544a|\u767b\u5f55|\u6ce8\u518c|"
    r"home|next|previous|more|login|sign in|procurement notices|tender notices)$",
    re.IGNORECASE,
)
BODY_SELECTORS = (
    '[itemprop="articleBody"]',
    ".notice-content",
    ".detail-content",
    ".detail_content",
    ".article-content",
    ".article_content",
    ".articleContent",
    ".articlecon",
    ".article_con",
    ".TRS_Editor",
    ".v_news_content",
    ".wp_articlecontent",
    "#vsb_content",
    "#vsb_content_2",
    "#zoom",
    "#zoomcon",
    "#content",
    "article",
)
DATE_SELECTORS = (
    'meta[name="PubDate"]',
    'meta[name="pubdate"]',
    'meta[name="publishdate"]',
    'meta[name="publication_date"]',
    'meta[property="article:published_time"]',
    'meta[name="DC.date.issued"]',
    'meta[name="ArticlePublishTime"]',
    "time[datetime]",
    '[itemprop="datePublished"]',
    ".publish-time",
    ".publish_time",
    ".pubtime",
    ".publication-date",
    ".article-date",
    ".article_date",
    ".arti_update",
    "#pubTime",
    ".source-time",
    ".source_time",
    ".info-time",
)


@dataclass
class CatalogEntry:
    entry_id: str
    group: str
    row_number: int
    entry_url: str
    name: str
    metadata: dict[str, str]


@dataclass
class DetailCandidate:
    url: str
    title: str
    published_at: str
    basis: str


@dataclass
class ListInspection:
    title: str
    status: str
    reason: str
    candidates: list[DetailCandidate]


def load_catalog(path: Path, group: str) -> list[CatalogEntry]:
    entries = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        headers = next(reader, [])
        if headers.count("entryUrl") != 1:
            raise ValueError("catalog_requires_one_entryUrl_column")
        if len(set(headers)) != len(headers):
            raise ValueError("catalog_duplicate_columns_including_entryUrl")
        while True:
            row_number = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                break
            if not any(value.strip() for value in row):
                continue
            values = {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(headers)
            }
            if len(row) > len(headers):
                values["_extra_columns"] = json.dumps(
                    row[len(headers) :], ensure_ascii=True
                )
            url = values["entryUrl"]
            digest = hashlib.sha256(
                f"{group}\n{row_number}\n{url}".encode()
            ).hexdigest()[:16]
            entries.append(
                CatalogEntry(
                    f"{group}:{row_number}:{digest}",
                    group,
                    row_number,
                    url,
                    values.get("name", ""),
                    values,
                )
            )
    return entries


def validate_entry(entry: CatalogEntry) -> str | None:
    url = entry.entry_url
    if not url:
        return "empty_entry_url"
    if url != url.strip() or re.search(r"[\x00-\x20\x7f\\]", url):
        return "invalid_url_characters"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
        if (
            parts.scheme not in {"http", "https"}
            or not host
            or parts.username is not None
            or parts.password is not None
        ):
            return "invalid_url"
        if port not in {None, 80, 443}:
            return "nonstandard_port"
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return "local_hostname"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            ascii_host = host.encode("idna").decode()
            if (
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", ascii_host)
                or ".." in ascii_host
            ):
                return "invalid_hostname"
        else:
            if not address.is_global:
                return "nonpublic_ip_literal"
    except (ValueError, UnicodeError):
        return "invalid_url"
    return None


def historical_restriction(entry: CatalogEntry) -> str | None:
    values = entry.metadata
    evidence = []
    if values.get("loginRequired", "").strip().casefold() in {
        "yes",
        "true",
        "1",
        "\u662f",
        "\u9700\u8981\u767b\u5f55",
        "\u9700\u767b\u5f55",
    }:
        evidence.append("loginRequired=" + values["loginRequired"])
    if values.get("httpStatus", "").strip() in {"401", "403", "429"}:
        evidence.append("httpStatus=" + values["httpStatus"])
    status = values.get("verificationStatus", "")
    uncertain = re.search(
        r"\u4e0d\u7b49\u4e8e|\u672a\u6838\u9a8c|\u5f85\u6838\u9a8c|\u4e0d\u9700|not |unknown|unverified",
        status,
        re.IGNORECASE,
    )
    explicit = re.search(
        r"\u660e\u786e\u9700\u767b\u5f55|\u5fc5\u987b\u767b\u5f55|\u767b\u5f55\u540e\u53ef\u89c1|\u8bbf\u95ee\u53d7\u9650|"
        r"\u7981\u6b62\u8bbf\u95ee|login required|access denied|rate.limit",
        status,
        re.IGNORECASE,
    )
    if explicit and not uncertain:
        evidence.append("verificationStatus=" + status)
    if not evidence:
        return None
    return (
        "historical_restriction;checkedOn="
        + values.get("checkedOn", "unknown")
        + ";"
        + ";".join(evidence)
    )


def _text(node: Tag | BeautifulSoup | None) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _date(value: str) -> str:
    found = re.search(
        r"(?<!\d)((?:19|20)\d{2})\s*[-/\.\u5e74]\s*(\d{1,2})\s*[-/\.\u6708]\s*(\d{1,2})(?!\d)",
        value,
    )
    if found:
        try:
            parsed = date(*map(int, found.groups()))
            return (
                parsed.isoformat()
                if parsed <= datetime.now().astimezone().date()
                else ""
            )
        except ValueError:
            pass
    return ""


def _garbled(value: str) -> bool:
    return (
        value.count("\ufffd") >= 2 and value.count("\ufffd") / max(len(value), 1) > 0.02
    )


def _clean_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, noscript, template"):
        node.decompose()
    return soup


def _restriction(soup: BeautifulSoup) -> str | None:
    title = _text(soup.title)
    visible = _text(soup)
    gate = re.compile(
        r"access denied|forbidden|login required|sign in required|security check|verify (?:that )?you|captcha|"
        r"too many requests|rate limit|\u8bbf\u95ee\u8fc7\u4e8e\u9891\u7e41|\u8bf7\u6c42\u8fc7\u4e8e\u9891\u7e41|"
        r"\u8bbf\u95ee\u53d7\u9650|\u7981\u6b62\u8bbf\u95ee|\u8bbf\u95ee\u62d2\u7edd|\u4eba\u673a\u9a8c\u8bc1|"
        r"\u5b89\u5168\u9a8c\u8bc1|\u8bf7\u5b8c\u6210\u9a8c\u8bc1\u7801|\u8bf7\u5148\u767b\u5f55|\u9700\u8981\u767b\u5f55",
        re.IGNORECASE,
    )
    if gate.search(title) or (len(visible) < 800 and gate.search(visible)):
        return "access_or_challenge_page"
    if soup.select_one(
        'form input[type="password"], #challenge-form, .cf-challenge, iframe[src*="captcha"]'
    ):
        return "login_or_challenge_form"
    return None


def _profile_for_list(url: str) -> str | None:
    parts = urlsplit(url)
    for sid, profile in PROFILES.items():
        known = urlsplit(profile.entry)
        if (
            parts.hostname == known.hostname
            and parts.path == known.path
            and parts.query == known.query
        ):
            return sid
    return None


def _candidate_url(href: str, url: str) -> tuple[str | None, str | None]:
    if not href or href.startswith("#") or ASSET.search(href):
        return None, "attachment_or_empty_link"
    target = urldefrag(urljoin(url, href))[0]
    issue = validate_entry(CatalogEntry("", "", 0, target, "", {}))
    if issue:
        return None, issue
    source, destination = urlsplit(url), urlsplit(target)
    if destination.hostname != source.hostname:
        return None, "cross_host_notice_links"
    if source.scheme == "https" and destination.scheme != "https":
        return None, "https_downgrade_link"
    if target == urldefrag(url)[0] or re.search(
        r"/(?:login|search)(?:[/.?]|$)", destination.path, re.IGNORECASE
    ):
        return None, "navigation_link"
    return target, None


def _row_date(anchor: Tag) -> str:
    # Stop at the nearest compact record, never borrow a page/footer date.
    for parent in [anchor, *list(anchor.parents)[:3]]:
        if not isinstance(parent, Tag) or parent.name in {
            "[document]",
            "body",
            "html",
            "nav",
            "header",
            "footer",
            "ul",
            "ol",
            "table",
        }:
            break
        if len(parent.select("a[href]")) > 3 or parent.select_one("nav,header,footer"):
            break
        value = _date(_text(parent))
        if not value:
            for clock in parent.select("time[datetime]"):
                value = _date(str(clock.get("datetime", "")))
                if value:
                    break
        if value:
            return value
        if parent.name in {"li", "tr", "dd"}:
            break
    return ""


def inspect_list(html: str, url: str) -> ListInspection:
    soup = _clean_soup(html)
    title = _text(soup.title)
    restriction = _restriction(soup)
    if restriction:
        return ListInspection(title, "restricted", restriction, [])
    if _garbled(_text(soup)):
        return ListInspection(title, "needs_adapter", "garbled_text", [])
    candidates = []
    reasons = []
    seen = set()
    profile = _profile_for_list(url)
    if profile:
        try:
            records = parse_list(profile, html, url).records
        except (ValueError, KeyError, TypeError):
            records = []
        for record in records:
            target, issue = _candidate_url(str(record.get("detailUrl", "")), url)
            label = str(record.get("listTitle", "")).strip()
            published = _date(str(record.get("listPublishedAt", "")))
            if issue:
                reasons.append(issue)
            if target and label and published and target not in seen:
                seen.add(target)
                candidates.append(
                    DetailCandidate(
                        target,
                        label,
                        published,
                        "verified_profile:" + profile + "+row_date",
                    )
                )
    if not candidates:
        for anchor in soup.select("a[href]"):
            if anchor.find_parent(["nav", "header", "footer"]):
                continue
            template_label = henan_list_title(anchor, url)
            label = (
                str(anchor.get("title") or _text(anchor)).strip()
                if template_label is None
                else template_label
            )
            if (
                len(label) < 10
                or SKIP_LINK.fullmatch(label)
                or not NOTICE.search(label)
            ):
                continue
            published = _row_date(anchor)
            if not published:
                continue
            target, issue = _candidate_url(str(anchor.get("href", "")), url)
            if issue:
                reasons.append(issue)
            if target and target not in seen:
                seen.add(target)
                candidates.append(
                    DetailCandidate(
                        target, label, published, "static_notice_link+row_date"
                    )
                )
    if candidates:
        return ListInspection(
            title,
            "candidate_list",
            "static_candidates_require_detail_checks",
            candidates,
        )
    if "cross_host_notice_links" in reasons:
        reason = "cross_host_notice_links"
    elif ASSET.search(html) and NOTICE.search(_text(soup)):
        reason = "attachment_requires_adapter"
    elif len(_text(soup)) < 80 and re.search(
        r"<script\b|id=[\"'](?:app|root)[\"']", html, re.IGNORECASE
    ):
        reason = "js_shell_or_dynamic_list"
    else:
        reason = "no_static_dated_notice_links"
    return ListInspection(title, "needs_adapter", reason, [])


def _publication_date(soup: BeautifulSoup) -> str:
    for selector in DATE_SELECTORS:
        for node in soup.select(selector):
            if _publication_chrome(node) or any(
                _publication_chrome(child) for child in node.find_all(True)
            ):
                continue
            value = _date(
                str(node.get("content") or node.get("datetime") or _text(node))
            )
            if value:
                return value
    for node in soup.select("span, p, div"):
        if (
            _publication_chrome(node)
            or any(_publication_chrome(child) for child in node.find_all(True))
            or len(node.select("a")) > 2
        ):
            continue
        text = _text(node)
        if len(text) < 180 and re.search(
            r"\u53d1\u5e03(?:\u65e5\u671f|\u65f6\u95f4)|\u516c\u544a\u65e5\u671f|published(?: on| at)?\s*:",
            text,
            re.IGNORECASE,
        ):
            value = _date(text)
            if value:
                return value
    return ""


def _publication_chrome(node: Tag) -> bool:
    for current in [node, *node.parents]:
        if not isinstance(current, Tag):
            continue
        if current.name in {"nav", "header", "footer"}:
            return True
        identity = str(current.get("id", "")) + " " + " ".join(current.get("class", []))
        if re.search(
            r"foot|copyright|navigation|navbar|\u7248\u6743|\u5bfc\u822a",
            identity,
            re.IGNORECASE,
        ):
            return True
    return False


def _detail_title(soup: BeautifulSoup) -> str:
    for selector in (
        'meta[name="ArticleTitle"]',
        '[itemprop="headline"]',
        "h1",
        ".arti_title",
        ".article-title",
        ".detail-title",
    ):
        node = soup.select_one(selector)
        if node and not node.find_parent(["nav", "header", "footer"]):
            value = str(node.get("content") or _text(node)).strip()
            if value:
                return value
    return ""


def _body_text(node: Tag) -> str:
    copy = BeautifulSoup(str(node), "html.parser")
    for child in copy.select(
        "script,style,noscript,nav,header,footer,form,h1,h2,time,button"
    ):
        child.decompose()
    return _text(copy)


def _non_link_body_text(node: Tag) -> str:
    copy = BeautifulSoup(str(node), "html.parser")
    for child in copy.select(
        "script,style,noscript,nav,header,footer,form,h1,h2,time,button,a"
    ):
        child.decompose()
    return _text(copy)


def inspect_detail(html: str, url: str, candidate: DetailCandidate) -> dict:
    value = {
        "title": "",
        "publishedAt": "",
        "content": "",
        "contentMode": "unknown",
        "status": "needs_adapter",
        "reason": "",
    }

    def rejected(reason, status="needs_adapter"):
        value.update(status=status, reason=reason)
        return value

    if urldefrag(url)[0] != urldefrag(candidate.url)[0]:
        return rejected("candidate_url_mismatch")
    soup = _clean_soup(html)
    restriction = _restriction(soup)
    if restriction:
        return rejected(restriction, "restricted")
    if _garbled(_text(soup)):
        return rejected("garbled_text", "body_incomplete")
    body = None
    profile = None
    if candidate.basis.startswith("verified_profile:"):
        profile = candidate.basis.split(":", 1)[1].split("+", 1)[0]
        if (
            profile not in PROFILES
            or urlsplit(url).hostname not in PROFILES[profile].hosts
        ):
            return rejected("profile_scope_mismatch")
        detail = parse_detail(profile, html, url)
        value.update(
            title=detail.title,
            publishedAt=_date(detail.published_at),
            content=detail.content,
            contentMode="html_profile",
        )
        issue = validate_detail(
            detail,
            {
                "listTitle": candidate.title,
                "listPublishedAt": candidate.published_at,
                "detailUrl": candidate.url,
            },
            source_id=profile,
        )
        if detail.mode == "iframe_shell":
            return rejected("structured_frame_requires_adapter")
        if issue and issue not in {
            "missing_body",
            "missing_detail_date",
            "title_mismatch",
        }:
            return rejected(issue, "body_incomplete")
        chosen = (
            PROFILES["ccgp"]
            if urlsplit(url).hostname == "www.ccgp.gov.cn"
            else PROFILES[profile]
        )
        body = soup.select_one(chosen.body)
        if body:
            value["content"] = _body_text(body)
    else:
        extracted = None
        for template_id, extractor in (
            ("university", university_detail),
            ("henan", henan_detail),
            ("zjnu", zjnu_detail),
        ):
            extracted = extractor(soup, url)
            if extracted is not None:
                title, publication, body = extracted
                value.update(
                    title=title,
                    publishedAt=_date(publication),
                    contentMode="html_template_candidate",
                    templateId=template_id,
                )
                break
        if extracted is None:
            value.update(
                title=_detail_title(soup),
                publishedAt=_publication_date(soup),
                contentMode="html_candidate",
            )
            for selector in BODY_SELECTORS:
                body = soup.select_one(selector)
                if body:
                    break
        if body:
            value["content"] = _body_text(body)
    if not value["title"]:
        return rejected("missing_detail_title")
    if not titles_consistent(value["title"], candidate.title):
        return rejected("title_mismatch")
    if not value["publishedAt"]:
        return rejected("missing_publication_date")
    if value["publishedAt"] != candidate.published_at:
        return rejected("publication_date_mismatch")
    if body:
        if any(
            re.search(
                r"\.pdf(?:[?#]|$)",
                str(node.get("src") or node.get("data") or ""),
                re.IGNORECASE,
            )
            for node in body.select("iframe[src],object[data],embed[src]")
        ):
            return rejected("pdf_requires_adapter", "body_incomplete")
        if len(value["content"]) < 500 and re.search(
            r"\u8be6\u89c1\u539f\u6587|\u67e5\u770b\u539f\u6587|\u70b9\u51fb\u539f\u6587|view original|read original",
            _text(body),
            re.IGNORECASE,
        ):
            return rejected("original_pointer", "body_incomplete")
        if body.select_one("iframe,object,embed"):
            return rejected("embedded_body_requires_adapter", "body_incomplete")
    if not body or not value["content"]:
        return rejected("missing_notice_body", "body_incomplete")
    if len(value["content"]) < 100:
        return rejected("body_too_short", "body_incomplete")
    prose = _non_link_body_text(body)
    if len(prose) < 100 or len(prose) / len(value["content"]) < 0.5:
        return rejected("navigation_or_link_only_body", "body_incomplete")
    if not BODY_NOTICE.search(prose):
        return rejected("notice_body_semantics_unverified", "body_incomplete")
    if not profile and not NOTICE.search(value["title"]):
        return rejected("notice_semantics_unverified")
    value.update(
        status="sample_readable",
        reason="static_profile_sample_not_native_run"
        if profile
        else "static_candidate_not_signed_rule",
    )
    return value
