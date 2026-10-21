"""Source-specific parsing, isolated from the published collection runtime."""

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from itertools import zip_longest
from urllib.parse import parse_qs, urldefrag, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from extrio.harvest import discover_records_from_spec, selector_value, titles_consistent


@dataclass(frozen=True)
class Profile:
    name: str
    entry: str
    hosts: frozenset[str]
    items: str
    title: str
    date: str
    link: str
    next_link: str
    detail_title: str
    detail_date: str
    body: str


PROFILES = {
    "ccgp": Profile(
        "中国政府采购网",
        "http://www.ccgp.gov.cn/cggg/zygg/",
        frozenset({"www.ccgp.gov.cn"}),
        "ul.c_list_bid > li",
        "a::attr(title)",
        "em:not([rel])::text",
        "a::attr(href)",
        "a.next",
        "h2.tc::text",
        "#pubTime::text",
        ".vF_detail_content",
    ),
    "csg": Profile(
        "南方电网",
        "http://www.bidding.csg.cn/zbcg/index.jhtml",
        frozenset({"www.bidding.csg.cn"}),
        'div.List2 > ul > li:has(> a[target="_blank"])',
        'a[target="_blank"]::attr(title)',
        "span.Right span.Gray::text",
        'a[target="_blank"]::attr(href)',
        'a:-soup-contains("下一页")',
        "h1.s-title::text",
        ".s-date::text",
        ".s-content > .Content",
    ),
    "fudan": Profile(
        "复旦大学",
        "https://czzx.fudan.edu.cn/cggg/list.htm",
        frozenset({"czzx.fudan.edu.cn", "www.ccgp.gov.cn"}),
        "#wp_news_w6 ul.news_list > li",
        "span.news_title a::attr(title)",
        "span.news_meta::text",
        "span.news_title a::attr(href)",
        "a.next",
        "h1.arti_title::text",
        ".arti_update::text",
        ".wp_articlecontent",
    ),
    "xmu": Profile(
        "厦门大学",
        "https://ztb.xmu.edu.cn/cghw/index.chtml",
        frozenset({"ztb.xmu.edu.cn", "www.ccgp.gov.cn"}),
        "#datab dd",
        "a::attr(title)",
        "span.date::text",
        "a::attr(href)",
        'a[rel="next"]',
        ".ctitle h1::text",
        ".ctitle .info i::text",
        ".ccontent",
    ),
    "hospital": Profile(
        "浙大一院",
        "https://www.zy91.com/general/list?right_cid=192&cid=193",
        frozenset({"www.zy91.com"}),
        "ul#pageBox > li",
        "h3.tit::text",
        "span.time::text",
        "a::attr(href)",
        'a[rel="next"]',
        "h1::text",
        ".bottom-blue .tag span:not(.eye)::text",
        ".bottom-blue .info",
    ),
    "agency": Profile(
        "广东省机电设备招标中心",
        "http://www.gdebidding.com/cgxx/index.jhtml",
        frozenset({"www.gdebidding.com", "eps.gdebidding.com"}),
        ".xs9 .border-bottom",
        "a::attr(title)",
        "span.float-right::text",
        "a::attr(href)",
        'a:-soup-contains("下一页")',
        "h1::text",
        "time::text",
        ".notice-content",
    ),
}


@dataclass
class Page:
    records: list[dict]
    next_url: str | None


@dataclass
class Detail:
    title: str = ""
    published_at: str = ""
    content: str = ""
    mode: str = "html"
    pdf_urls: list[str] = field(default_factory=list)
    original_urls: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    frame_url: str | None = None
    original_title: str | None = None
    fields: dict = field(default_factory=dict)


def canonical_url(url: str, profile: Profile) -> str:
    url = urldefrag(url)[0]
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or p.hostname not in profile.hosts or p.username or p.password or p.port not in {None, 80, 443}:
        raise ValueError("url_outside_exact_scope")
    return url


def with_query(url: str, **values) -> str:
    p = urlsplit(url)
    query = {k: v[-1] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
    query.update({k: str(v) for k, v in values.items()})
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ""))


def _field(selector):
    return {"selector": "css:" + selector, "required": True, "multipleMatchPolicy": "first", "transforms": ["trim", "collapse_whitespace"]}


def list_spec(sid: str) -> dict:
    p = PROFILES[sid]
    return {
        "itemsSelector": "css:" + p.items,
        "fields": {"listTitle": _field(p.title), "listPublishedAt": _field(p.date), "detailUrl": _field(p.link)},
        "pagination": {"type": "next_link", "selector": "css:" + p.next_link, "maxPages": 3, "allowCrossHost": False},
    }


def parse_list(sid: str, html: str, url: str) -> Page:
    profile = PROFILES[sid]
    canonical_url(url, profile)
    if sid == "hospital" and urlsplit(url).path == "/content/get_article":
        data = json.loads(html)
        if data.get("code") != 1:
            raise ValueError("public_api_unsuccessful")
        records = []
        for row in data["data"]["list"]:
            if str(row["category_id"]) != "193" or not str(row["id"]).isdigit():
                raise ValueError("unexpected_api_category_or_id")
            records.append(
                {
                    "listTitle": row["title"],
                    "listPublishedAt": row["public_time"],
                    "detailUrl": urljoin(url, f"/content/default/193/{row['id']}"),
                }
            )
        number = int(parse_qs(urlsplit(url).query)["page"][0])
        return Page(records, with_query(url, page=number + 1) if records else None)
    records, next_url = discover_records_from_spec(html, url, list_spec(sid))
    soup = BeautifulSoup(html, "html.parser")
    if sid == "csg":
        full_titles = {}
        for anchor in soup.select("a[href][title]"):
            target = urljoin(url, anchor["href"])
            value = anchor["title"].strip()
            if value and not value.endswith(("...", "…")):
                full_titles.setdefault(target, set()).add(value)
        for node, record in zip(soup.select(profile.items), records, strict=True):
            display = selector_value(node, 'a[target="_blank"]::text', url)
            candidates = full_titles.get(record["detailUrl"], set())
            record["listTitle"] = next(iter(candidates)) if len(candidates) == 1 else record["listTitle"] or display
            record["displayTitle"] = display
            record["titleEvidence"] = "same_url_title_attribute" if len(candidates) == 1 else "display_text"
    if sid == "ccgp":
        scripts = "\n".join(n.get_text() for n in soup.select("script"))
        config = re.search(r"Pager\(\{\s*size:(\d+),\s*current:(\d+),\s*prefix:'index',\s*suffix:'htm'\s*\}\)", scripts)
        if config:
            size, current = map(int, config.groups())
            expected = re.search(r"index_(\d+)\.htm$", urlsplit(url).path)
            if current == (int(expected[1]) if expected else 0) and 0 <= current < size - 1 <= 10000:
                next_url = urljoin(url, f"index_{current + 1}.htm")
    elif sid == "xmu":
        current, total = soup.select_one("#hcurPage"), soup.select_one("#rowTotal")
        if current and total and str(current.get("value", "")).isdigit() and str(total.get("value", "")).isdigit():
            number = int(current["value"])
            requested = int(parse_qs(urlsplit(url).query).get("curPage", ["1"])[0])
            if number == requested and 1 <= number < math.ceil(int(total["value"]) / 15):
                next_url = with_query(PROFILES[sid].entry, curPage=number + 1)
    elif sid == "hospital":
        if re.search(r"pagedata\('\d+','193','pageBox','list','articles',10\)", html):
            next_url = urljoin(url, "/content/get_article?page=2&cid=193&cur=10")
    if next_url:
        next_url = canonical_url(next_url, profile)
        if urlsplit(next_url).hostname != urlsplit(profile.entry).hostname:
            raise ValueError("cross_host_list_pagination")
    return Page(records, next_url)


def text_of(node) -> str:
    if not node:
        return ""
    for child in node.select("script,style,noscript"):
        child.decompose()
    return " ".join(node.get_text(" ", strip=True).split())


def notice_stage_from_url(url: str) -> str | None:
    path = urlsplit(url).path
    if "/gzgg/" in path:
        return "correction"
    if any(f"/{kind}/" in path for kind in ("gkzb", "jzxcs", "jzxtp", "xjgg")):
        return "procurement"
    return None


def parse_detail(sid: str, html: str, url: str) -> Detail:
    profile = PROFILES["ccgp"] if urlsplit(url).hostname == "www.ccgp.gov.cn" else PROFILES[sid]
    soup = BeautifulSoup(html, "html.parser")
    detail = Detail(title=selector_value(soup, profile.detail_title, url), published_at=selector_value(soup, profile.detail_date, url))
    body = soup.select_one(profile.body)
    detail.content = text_of(body)
    if profile is PROFILES["ccgp"]:
        detail.fields["noticeStage"] = notice_stage_from_url(url)
        labels = {
            "采购项目名称": "projectName",
            "采购单位": "buyer",
            "行政区域": "region",
            "预算金额": "budgetRaw",
            "代理机构名称": "agency",
        }
        for label in soup.select("div.table td.title"):
            key = labels.get(label.get_text(strip=True))
            value = label.find_next_sibling("td")
            if key and value:
                detail.fields.setdefault(key, text_of(value))
    if sid == "csg":
        breadcrumb = soup.select_one(".W1200.Center.Top18")
        if breadcrumb:
            detail.fields["breadcrumbTitle"] = breadcrumb.get_text(" ", strip=True).rsplit(">", 1)[-1].strip()
    if body:
        for node in body.select("a[href],iframe[src],object[data],embed[src]"):
            target = urljoin(url, node.get("href") or node.get("src") or node.get("data"))
            if re.search(r"\.(pdf|docx?|xlsx?|zip)(?:[?#]|$)", target, re.I):
                detail.attachments.append(target)
            if node.name in {"iframe", "object", "embed"} and re.search(r"\.pdf(?:[?#]|$)", target, re.I):
                detail.pdf_urls.append(target)
            if urlsplit(target).hostname == "www.ccgp.gov.cn" and urlsplit(target).path.startswith("/cggg/"):
                detail.original_urls.append(target)
    if detail.original_urls and len(detail.content) < 500:
        detail.mode = "original_pointer"
    if sid == "agency":
        frame = soup.select_one("iframe#iframepage[src]")
        if frame:
            detail.frame_url = urljoin(url, frame["src"])
            detail.mode = "iframe_shell"
    # Dates are taken from the detail's publication metadata, never its footer.
    match = re.search(r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})", detail.published_at)
    if match:
        try:
            detail.published_at = date(*map(int, match.groups())).isoformat()
        except ValueError:
            detail.published_at = ""
    return detail


def validate_detail(detail: Detail, record: dict, *, source_id: str | None = None) -> str | None:
    if not detail.title:
        return "missing_detail_title"
    agency_identity = detail.mode == "public_structured_fields" and detail.fields.get("guidAndTemplateIdentityVerified") is True
    list_title = record.get("listTitle", "")
    title_match = titles_consistent(detail.title, list_title)
    if not title_match and source_id == "csg" and list_title.endswith(("...", "…")):
        prefix = re.sub(r"\s+", "", unicodedata.normalize("NFKC", list_title.rstrip(". …")))
        full = re.sub(r"\s+", "", unicodedata.normalize("NFKC", detail.title))
        date_match = detail.published_at == record.get("listPublishedAt", "")[:10]
        breadcrumb_match = titles_consistent(detail.title, detail.fields.get("breadcrumbTitle", ""))
        title_match = len(prefix) >= 40 and full.startswith(prefix) and date_match and breadcrumb_match
        if title_match:
            detail.fields["titleMatchPolicy"] = "long_truncated_prefix_and_date_and_breadcrumb"
    if not list_title or (not agency_identity and not title_match):
        return "title_mismatch"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", detail.published_at):
        return "missing_detail_date"
    if detail.mode == "original_pointer":
        return "original_not_resolved"
    if not detail.content:
        return "missing_body"
    return None


def agency_resource(frame_url: str, frame_html: str) -> tuple[str, str]:
    canonical_url(frame_url, PROFILES["agency"])
    parts = urlsplit(frame_url)
    guid = parse_qs(parts.query).get("guid", [""])[0]
    if parts.hostname != "eps.gdebidding.com" or not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", guid):
        raise ValueError("unexpected_public_frame_guid")
    root = "/gdjd-xunjia/gonggaoxinxi/"
    endpoints = {root + "gongGao_view.html": "queryXiangMuByGuid.do", root + "jieGuo_view.html": "queryCGGLJieGuoByGuid.do"}
    endpoint = endpoints.get(parts.path)
    if not endpoint or root + endpoint + "?guid=" not in frame_html:
        raise ValueError("unknown_public_frame_template")
    return urljoin(frame_url, root + endpoint + "?" + urlencode({"guid": guid})), guid


def parse_agency_data(data: dict, record: dict, guid: str, *, result: bool) -> Detail:
    project = data.get("xiangMu") if result else data
    if not isinstance(project, dict) or data.get("jieGuoGuid" if result else "xiangMuGuid") != guid:
        raise ValueError("public_data_guid_mismatch")
    if result and (data.get("hideForBidder") is True or data.get("isGongKai") is False):
        raise ValueError("result_visibility_requires_review")
    project_name = str(project.get("xiangMuName") or "").strip()
    if not project_name:
        raise ValueError("missing_public_project_name")
    packages = [data["baoJian"]] if result and isinstance(data.get("baoJian"), dict) else project.get("lsBaoJian") or []
    if result:
        expected_titles = [project_name + "成交结果公告"]
        for package in packages:
            code = str(package.get("baoJianBianHao") or "").rsplit("/", 1)[-1]
            if code.isdigit():
                expected_titles.append(project_name + f"(包件{code})成交结果公告")
        title = project_name + str(project.get("caiGouTypeText") or "") + "成交结果公告"
        published = str(data.get("gongShiFaBuTimeShortText") or "")
    else:
        kind = {1: "采购", 2: "询价", 3: "竞价", 4: "竞价", 5: "采购", 6: "采购", 7: "采购", 8: "采购", 11: "竞价"}
        suffix = kind.get(project.get("caiGouType"))
        if not suffix:
            raise ValueError("unsupported_public_procurement_type")
        title = project_name + suffix + "公告"
        expected_titles = [project_name, title]
        published = str(project.get("xunJiaStartTimeText" if project.get("caiGouType") == 2 else "gongGaoStartTimeText") or "")[:10]
    verified = any(titles_consistent(value, record.get("listTitle", "")) for value in expected_titles)
    fields = {
        "projectName": project_name,
        "projectNumber": project.get("xiangMuBianHao"),
        "buyer": project.get("caiGouRenName"),
        "agency": project.get("caiGouDaiLiName"),
        "procurementMethodRaw": project.get("caiGouTypeText"),
        "noticeType": "result" if result else "procurement",
        "guidAndTemplateIdentityVerified": verified,
        "packages": [{k: p.get(k) for k in ("baoJianName", "baoJianBianHao", "caiGouGuSuanJia") if p.get(k) is not None} for p in packages],
    }
    if not result:
        fields["deadlineRaw"] = project.get("zuiZhongGongGaoEndTimeText")
    # Keep only public announcement fields. Do not serialize the entire response:
    # it also contains audit, account and conditional-visibility data.
    public_fields = {k: v for k, v in fields.items() if k != "guidAndTemplateIdentityVerified"}
    content = json.dumps(public_fields, ensure_ascii=False)
    if project.get("gongGaoContent") and not result:
        content += "\n" + text_of(BeautifulSoup(str(project["gongGaoContent"]), "html.parser"))
    return Detail(title=title, published_at=published, content=content, mode="public_structured_fields", fields=fields)


def sample_records(pages: list[list[dict]], limit: int) -> list[dict]:
    # Round-robin sampling exercises every fetched page instead of only page one.
    selected, seen = [], set()
    for row in zip_longest(*pages):
        for record in row:
            if not record or record["detailUrl"] in seen:
                continue
            seen.add(record["detailUrl"])
            selected.append(record)
            if len(selected) >= limit:
                return selected
    return selected
