"""Signed publisher profiles. Envelopes are derived evidence, never original DOM."""

import asyncio
import hashlib
import json
import re
import sys
import unicodedata
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, UnicodeDammit

from extrio.harvest import selector_value, titles_consistent
from extrio.source_network import SourceNetworkError

RESOLUTION = "official_notice_v1"
RESOLUTION_V2 = 'official_notice_v2'
RESOLUTION_V3 = 'official_notice_v3'
ORIGINAL_DATE_PROFILES = {RESOLUTION_V2, RESOLUTION_V3}
PROFILES = {
    "czzx.fudan.edu.cn": ("h1.arti_title::text", ".arti_update::text", ".wp_articlecontent", "www.ccgp.gov.cn"),
    "ztb.xmu.edu.cn": (".ctitle h1::text", ".ctitle .info i::text", ".ccontent", "www.ccgp.gov.cn"),
    "www.gdebidding.com": ("", "", "", "eps.gdebidding.com"),
}
ENTRY_PATHS = {'czzx.fudan.edu.cn': '/cggg/list.htm', 'ztb.xmu.edu.cn': '/cghw/index.chtml',
               'www.gdebidding.com': '/cgxx/index.jhtml'}
GUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def supports_resolution(url: str) -> bool:
    p = urlsplit(url)
    return p.hostname in ENTRY_PATHS and p.path == ENTRY_PATHS[p.hostname]


def profile_hosts(source_url: str) -> set[str]:
    host = urlsplit(source_url).hostname or ""
    return {host, PROFILES[host][3]} if host in PROFILES else {host}


def validate_resolution(spec: dict) -> None:
    detail = spec["collect"].get("detail", {})
    if not detail.get("resolution"):
        return
    entry = spec["sourceContext"]["entrypoints"][0]
    if (detail["resolution"] not in {RESOLUTION, RESOLUTION_V2, RESOLUTION_V3} or not supports_resolution(entry)
            or (detail['resolution'] == RESOLUTION_V3 and urlsplit(entry).hostname != 'www.gdebidding.com')
            or set(spec["sourceContext"]["allowedHosts"]) != profile_hosts(entry)
            or detail["responseType"] != "json" or detail.get("transport", "http") != "http"):
        raise SourceNetworkError("invalid_official_resolution_scope")
    if any(not f["selector"].startswith("jsonpath:") for f in detail["fields"].values()):
        raise SourceNetworkError("official_resolution_requires_json_fields")


def text(node) -> str:
    if not node:
        return ""
    for child in node.select("script,style,noscript"):
        child.decompose()
    return " ".join(node.get_text(" ", strip=True).split())


def date_text(value: str) -> str:
    from datetime import date

    match = re.search(r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})", value)
    return date(*map(int, match.groups())).isoformat() if match else ""


def ccgp_notice(url: str) -> bool:
    p = urlsplit(url)
    return (p.scheme in {"http", "https"} and p.hostname == "www.ccgp.gov.cn" and not p.username and not p.password
            and p.port in {None, 443 if p.scheme == 'https' else 80}
            and bool(re.fullmatch(r"/cggg/[a-z]+/[a-z]+/\d{6}/t\d{8}_\d+\.htm", p.path)))


def https_original(url: str) -> str:
    if not ccgp_notice(url):
        raise ValueError('unexpected_original_notice_url')
    p = urlsplit(url)
    return urlunsplit(('https', 'www.ccgp.gov.cn', p.path, p.query, ''))


def notice_kinds(title):
    return ({'gzgg'} if any(word in title for word in ('更正', '澄清')) else {'zbgg', 'cjgg'}
                      if any(word in title for word in ('中标', '成交')) else {'fqgg', 'qtgg'}
                      if any(word in title for word in ('废标', '终止')) else {'gkzb', 'jzxcs', 'jzxtp', 'xjgg', 'qtgg'})


def original_identity(title: str, original_title: str, url: str, html: str, host: str) -> bool:
    kind = urlsplit(url).path.split('/')[3]
    expected_kinds = notice_kinds(title)
    if kind not in expected_kinds:
        return False
    if titles_consistent(title, original_title):
        return True
    if host != "ztb.xmu.edu.cn":
        return False
    stem = re.sub(r"(?:采购信息|采购更正信息|更正信息)(?:[（(]第[一二三四五六七八九十0-9]+次[）)])?$", "", title)
    expected = "gzgg" if "更正信息" in title else "procurement"
    kind = urlsplit(url).path.split("/")[3]
    stage_ok = kind == expected if expected == "gzgg" else kind in {"gkzb", "jzxcs", "jzxtp", "xjgg"}
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    for node in soup.select("div.table td.title"):
        sibling = node.find_next_sibling("td")
        if sibling:
            fields[text(node)] = text(sibling)
    return bool(stem != title and stem in original_title and stage_ok and fields.get("采购单位") == "厦门大学"
                and (titles_consistent(stem, fields.get("采购项目名称", "")) or any(
                    titles_consistent(stem + suffix, original_title) for suffix in ("公开招标公告", "采购项目公开招标公告"))))


def project_key(value):
    value = unicodedata.normalize('NFKC', value)
    value = re.sub(r'[（(](?:第)?[一二三四五六七八九十0-9]+次[）)]$', '', value)
    value = re.sub(r'(?:项目招标公告|采购更正信息|采购信息|更正信息|招标信息|公开招标公告|招标公告)$', '', value)
    value = value.replace('质谱联用仪和气相色谱质谱联用仪', '质谱联用仪及气相色谱质谱联用仪')
    value = value.replace('年度伙食供应', '年度伙食')
    return re.sub(r'\W', '', re.sub(r'采购$', '', value))


def original_identity_v2(title, original_title, url, soup, host, landing_body):
    if urlsplit(url).path.split('/')[3] not in notice_kinds(title):
        raise ValueError('linked_original_project_or_stage_mismatch')
    fields = {text(n): text(n.find_next_sibling('td')) for n in soup.select('div.table td.title')}
    buyer, project = fields.get('采购单位'), fields.get('采购项目名称', '')
    expected_buyer = {'ztb.xmu.edu.cn': '厦门大学', 'czzx.fudan.edu.cn': '复旦大学'}.get(host)
    shown, expected = project_key(title), project_key(project)
    if shown != expected and host == 'ztb.xmu.edu.cn' and project_key(project) in project_key(landing_body):
        shown = shown.replace('电影学院大楼多媒体系统设备', '电影学院新大楼多媒体系统设备')
    round_pattern = r'[（(](?:第)?([一二三四五六七八九十0-9]+)次[）)]'
    a, b = re.search(round_pattern, title), re.search(round_pattern, original_title)
    numerals = dict(zip('一二三四五六七八九十', map(str, range(1, 11)), strict=True))
    round_ok = not a or bool(b and numerals.get(a[1], a[1]) == numerals.get(b[1], b[1]))
    project_matches = ((len(expected) >= 8 and shown == expected)
                       or (len(expected) >= 4 and expected != project_key(buyer or '') and titles_consistent(title, original_title)))
    if not (buyer == expected_buyer and project_matches
            and expected in re.sub(r'\W', '', unicodedata.normalize('NFKC', original_title)) and round_ok):
        raise ValueError('linked_original_project_or_stage_mismatch')
    return {'identityMethod': 'publisher_link_buyer_exact_project', 'identityBuyer': buyer, 'identityProjectName': project}


def resolved_title_matches(url: str, envelope: dict, record: dict) -> bool:
    proof = envelope.get('resolution') or {}
    return bool(urlsplit(url).hostname == 'eps.gdebidding.com' and record.get('detailUrl') == url
                and proof.get('kind') == 'eps_public_template_render' and not proof.get('error')
                and proof.get('renderedTitle') == envelope.get('title') and any(
                    titles_consistent(record.get('listTitle', ''), label) for label in proof.get('identityListTitles', [])))


class OfficialDocuments:
    def __init__(self, network, source_url: str, write, *, profile=RESOLUTION):
        self.network = network
        self.host = urlsplit(source_url).hostname
        if not supports_resolution(source_url) or network.allowed_hosts != profile_hosts(source_url):
            raise SourceNetworkError("invalid_official_resolution_scope")
        self.write = write
        self.profile = profile
        self.asset_cache = {}
        self.asset_proof = {}
        self.asset_counter = 0
        self.browser = None
        self.playwright = None
        self.proxy = None

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        if self.proxy:
            self.proxy.close()
            await self.proxy.wait_closed()

    async def fetch(self, url: str, role: str, docs: list, prefix: str):
        response = (await self.network.fetch(url, respect_robots=True)).require_success()
        name = f"{prefix}-{len(docs) + 1:02d}." + ("pdf" if response.body.startswith(b"%PDF-") else "html")
        self.write(name, response.body)
        docs.append({"role": role, "url": response.url, "requestedUrl": url, "file": name,
                     "sha256": hashlib.sha256(response.body).hexdigest()})
        return response, UnicodeDammit(response.body).unicode_markup or response.body.decode("utf-8", errors="replace")

    async def resolve(self, record: dict, index: int) -> str:
        docs = []
        prefix = f"document-{index:03d}"
        value = {"schemaVersion": "extrio.official-document.v1", "title": "", "publishedAt": "", "content": "",
                 "resolution": {"profile": self.profile, "kind": "unresolved", "documents": docs, "error": None}}
        resolution = value["resolution"]
        try:
            url = record["detailUrl"]
            if self.host == "www.gdebidding.com":
                await self.eps(url, value, prefix)
            else:
                response, html = await self.fetch(url, "publisher_landing", docs, prefix)
                final = response.url
                if ccgp_notice(final):
                    published = date_text(str(record.get('listPublishedAt') or record.get('publishedAt') or ''))
                    await self.original(value, final, html, record.get("listTitle", ""),
                                        published if self.profile in ORIGINAL_DATE_PROFILES else None)
                else:
                    if urlsplit(final).hostname != self.host:
                        raise ValueError("unexpected_landing_host")
                    a, b, c, _ = PROFILES[self.host]
                    soup = BeautifulSoup(html, "html.parser")
                    value.update(title=selector_value(soup, a, final), publishedAt=date_text(selector_value(soup, b, final)))
                    body = soup.select_one(c)
                    body_text = text(body)
                    complete_amendment = (self.host == 'ztb.xmu.edu.cn' and '更正内容' in body_text
                                          and '其余内容不变' in body_text and bool(re.search('截止时间|开标时间', body_text)))
                    originals = list(dict.fromkeys(urljoin(final, n["href"]) for n in body.select("a[href]")
                                                   if ccgp_notice(urljoin(final, n["href"])))) if body else []
                    pdfs = list(dict.fromkeys(urljoin(final, n.get("src") or n.get("data"))
                                             for n in body.select("iframe[src],object[data],embed[src]")
                                             if re.search(r"\.pdf(?:[?#]|$)", n.get("src") or n.get("data"), re.I))) if body else []
                    if originals and len(body_text) < 500:
                        if len(originals) != 1:
                            raise ValueError("ambiguous_official_original")
                        # Upgrade only the exact publisher-emitted statutory URL.
                        target = https_original(originals[0])
                        r, original = await self.fetch(target, "publisher_linked_original", docs, prefix)
                        await self.original(value, r.url, original, value["title"], value["publishedAt"], body_text)
                    elif pdfs:
                        if len(pdfs) > 2:
                            raise ValueError("too_many_body_pdfs")
                        contents = []
                        for pdf_url in pdfs:
                            if urlsplit(pdf_url).hostname != self.host:
                                raise ValueError("pdf_host_outside_publisher")
                            r, _ = await self.fetch(pdf_url, "embedded_body_pdf", docs, prefix)
                            pdf = await self.pdf(r.body, allow_footer=self.profile in ORIGINAL_DATE_PROFILES)
                            docs[-1].update(pages=pdf["pages"], extraction=pdf["extraction"],
                                            textSha256=hashlib.sha256(pdf["text"].encode()).hexdigest())
                            if pdf.get('footerPages'):
                                docs[-1]['footerPages'] = pdf['footerPages']
                            contents.append(pdf["text"])
                        value["content"] = "\n".join(contents)
                        resolution["kind"] = "embedded_pdf_text"
                    elif (body and not body.select("iframe,object,embed") and len(body_text) >= 60
                          and not (not complete_amendment and len(body_text) < 500 and body.select('a[href]')
                                   and re.search('原文|详见|公告链接|公告网址', body_text))):
                        value["content"] = body_text
                        resolution["kind"] = "publisher_html"
                    else:
                        raise ValueError("missing_or_unsupported_notice_body")
            if not value["title"] or not value["publishedAt"] or len(value["content"].strip()) < 60:
                raise ValueError("incomplete_official_document")
            if not titles_consistent(value["title"], record.get("listTitle", "")) and not resolved_title_matches(url, value, record):
                raise ValueError("publisher_list_detail_identity_mismatch")
        except ValueError as exc:
            resolution["error"] = str(exc)[:200]
            value["content"] = ""
        except SourceNetworkError as exc:
            if str(exc) not in {"authentication_or_access_required", "http_status_404", "http_status_410",
                                "source_request_timed_out", "source_connection_failed"}:
                raise
            resolution["error"] = str(exc)
            value["content"] = ""
        resolution['redirects'] = [r for r in self.network.redirect_evidence if r['url'] == record['detailUrl']]
        return json.dumps(value, ensure_ascii=False)

    async def original(self, value: dict, url: str, html: str, landing_title: str, landing_date: str | None, landing_body=''):
        if not ccgp_notice(url):
            raise ValueError("unexpected_original_notice_url")
        soup = BeautifulSoup(html, "html.parser")
        title = selector_value(soup, "meta[name=ArticleTitle]::attr(content)", url) or selector_value(soup, "h2.tc::text", url)
        published = date_text(selector_value(soup, "meta[name=PubDate]::attr(content)", url) or selector_value(soup, "#pubTime::text", url))
        if self.profile in ORIGINAL_DATE_PROFILES:
            value['resolution'].update(original_identity_v2(landing_title, title, url, soup, self.host, landing_body))
        elif not original_identity(landing_title, title, url, html, self.host):
            raise ValueError("linked_original_project_or_stage_mismatch")
        if landing_date and (landing_date < published if self.profile in ORIGINAL_DATE_PROFILES else landing_date != published):
            raise ValueError("linked_original_publication_date_mismatch")
        value.update(title=landing_title, publishedAt=published, content=text(soup.select_one(".vF_detail_content")))
        value["resolution"].update(kind="publisher_linked_original", originalTitle=title, originalUrl=url)
        if self.profile in ORIGINAL_DATE_PROFILES:
            value['resolution'].update(originalPublishedAt=published, publisherPublishedAt=landing_date)

    @staticmethod
    async def pdf(data: bytes, *, allow_footer=False) -> dict:
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "extrio.pdf_document",
                                                      *(['--allow-known-footer'] if allow_footer else []),
                                                      stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.DEVNULL)
        pending = asyncio.create_task(process.communicate(data))
        try:
            async with asyncio.timeout(25):
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.25)
                    if sys.platform == 'darwin' and not pending.done():
                        # Darwin does not enforce RLIMIT_AS. Bound resident memory
                        # independently while keeping CPU and wall-clock limits.
                        monitor = await asyncio.create_subprocess_exec(
                            '/bin/ps', '-o', 'rss=', '-p', str(process.pid), stdout=asyncio.subprocess.PIPE)
                        rss, _ = await monitor.communicate()
                        if rss.strip().isdigit() and int(rss) > 512_000:
                            raise ValueError('pdf_memory_limit_exceeded')
                stdout, _ = await pending
        except (TimeoutError, asyncio.CancelledError, ValueError) as exc:
            if process.returncode is None:
                process.kill()
            await process.wait()
            await pending
            if isinstance(exc, TimeoutError):
                raise ValueError('pdf_parser_timed_out') from exc
            raise
        try:
            result = json.loads(stdout)
        except ValueError as exc:
            raise ValueError("pdf_parser_failed") from exc
        if result.get("error"):
            raise ValueError(result["error"])
        return result

    async def eps(self, url: str, value: dict, prefix: str):
        parts = urlsplit(url)
        guid = parse_qs(parts.query).get("guid", [""])[0]
        comparison = parts.path == '/gg/cmsGGDetailcg' and self.profile == RESOLUTION_V3
        if (parts.hostname != "eps.gdebidding.com" or not (parts.path == '/gg/cmsGGDetailjj' or comparison)
                or not GUID.fullmatch(guid) or (comparison and (parse_qs(parts.query).get('guid') != [guid]
                    or parse_qs(parts.query).get('pageName') != ['xbcg']))):
            raise ValueError("unsupported_eps_landing")
        docs = value["resolution"]["documents"]
        response, html = await self.fetch(url, "eps_landing", docs, prefix)
        frame = BeautifulSoup(html, "html.parser").select_one("iframe#iframepage[src]")
        if not frame:
            raise ValueError("eps_frame_missing")
        frame_url = urljoin(response.url, frame["src"])
        p = urlsplit(frame_url)
        root = "/gdjd-xunjia/gonggaoxinxi/"
        endpoints = {root + "gongGao_view.html": "queryXiangMuByGuid.do", root + "jieGuo_view.html": "queryCGGLJieGuoByGuid.do"}
        if p.hostname != "eps.gdebidding.com" or parse_qs(p.query).get("guid") != [guid] or p.path not in endpoints:
            raise ValueError("eps_frame_guid_or_template_mismatch")
        if comparison and p.path != root + 'gongGao_view.html':
            raise ValueError('eps_comparison_template_mismatch')
        _, template = await self.fetch(frame_url, "eps_public_template", docs, prefix)
        endpoint = root + endpoints[p.path]
        if endpoint + "?guid=" not in template:
            raise ValueError("eps_endpoint_not_in_template")
        api_url = urljoin(frame_url, endpoint + "?" + urlencode({"guid": guid}))
        r, raw = await self.fetch(api_url, "eps_public_get", docs, prefix)
        data = json.loads(raw)
        result = p.path.endswith("jieGuo_view.html")
        if data.get("jieGuoGuid" if result else "xiangMuGuid") != guid or data.get("isDeleted") is True:
            raise ValueError("eps_public_guid_mismatch")
        if result and (data.get("hideForBidder") is not False or data.get("isGongKai") is not True):
            raise ValueError("eps_visibility_requires_review")
        project = data.get("xiangMu") if result else data
        if not isinstance(project, dict) or not project.get("xiangMuName"):
            raise ValueError("eps_project_missing")
        if project.get('gongKaiType') != 10 or project.get('isTempGongGao') is True or project.get('isDeleted') is True:
            raise ValueError('eps_project_visibility_requires_review')
        if comparison and project.get('caiGouType') != 5:
            raise ValueError('eps_comparison_procurement_type_mismatch')
        cached_reads = {api_url: r.body}
        if not result:
            clock_url = 'https://eps.gdebidding.com/gdjd-xunjia/common/getSystemTime.do'
            clock, _ = await self.fetch(clock_url, 'eps_public_clock_get', docs, prefix)
            cached_reads[clock_url] = clock.body
            supplement_path = '/gdjd-xunjia/buyi/queryBuYiPagination.do'
            if supplement_path + '?xiangMuGuid=' not in template:
                raise ValueError('eps_supplement_template_changed')
            supplement_url = urljoin(frame_url, supplement_path + '?' + urlencode({'xiangMuGuid': guid, 'pingweiFlag': 1}))
            supplement, raw_supplement = await self.fetch(
                supplement_url + '&page=1&rows=50', 'eps_public_supplement_index_get', docs, prefix)
            supplement_data = json.loads(raw_supplement)
            rows = supplement_data.get('rows')
            if not isinstance(rows, list) or int(supplement_data.get('total', -1)) != len(rows) or len(rows) > 50:
                raise ValueError('eps_supplement_index_incomplete')
            if any(row.get('xiangMuGuid', guid) != guid for row in rows):
                raise ValueError('eps_supplement_project_mismatch')
            cached_reads[supplement_url] = supplement.body
        receive_guid = (data.get('baoJian') or {}).get('receiveGuid') if result else None
        if receive_guid:
            if (not re.fullmatch(r'(?:[0-9]{1,32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})', str(receive_guid))
                    or root + 'queryBJJSByReceiveGuid.do?receiveGuid=' not in template):
                raise ValueError('eps_unit_read_not_in_template')
            unit_url = urljoin(frame_url, root + 'queryBJJSByReceiveGuid.do?' + urlencode({'receiveGuid': receive_guid}))
            unit_response, _ = await self.fetch(unit_url, 'eps_public_unit_get', docs, prefix)
            cached_reads[unit_url] = unit_response.body
        visible, rendered = await self.render_eps(frame_url, template, api_url, cached_reads)
        title = visible.splitlines()[0].strip()
        project_name = ' '.join(project['xiangMuName'].split())
        if not project_name or project_name not in ' '.join(title.split()):
            raise ValueError("eps_rendered_title_project_mismatch")
        labels = []
        if result:
            stage = data.get('gongShiType')
            failed_result = (self.profile in ORIGINAL_DATE_PROFILES and stage == 2 and 'gongShiType()==2' in template
                             and '失败原因' in visible)
            if '成交结果公告' not in title or not (stage == 1 or failed_result):
                raise ValueError('eps_notice_stage_requires_review')
            if self.profile in ORIGINAL_DATE_PROFILES:
                value['resolution'].update(sourceStage=stage, noticeOutcome='failed' if failed_result else 'awarded')
            labels.append(project_name + '成交结果公告')
            package = data.get('baoJian') or {}
            package_code = str(package.get('baoJianBianHao') or '').rsplit('/', 1)[-1]
            if package_code.isdigit():
                labels.append(project_name + f'(包件{package_code})成交结果公告')
        else:
            suffix = {1: '采购', 2: '询价', 3: '竞价', 4: '竞价', 5: '采购', 6: '采购', 7: '采购', 8: '采购', 11: '竞价'}.get(
                project.get('caiGouType'))
            if not suffix or '公告' not in title or re.search('成交|结果|更正|终止|失败', title):
                raise ValueError('eps_procurement_stage_requires_review')
            labels.append(project_name + suffix + '公告')
            if comparison:
                if not titles_consistent(title, project_name + '公告'):
                    raise ValueError('eps_comparison_rendered_title_mismatch')
                labels.extend([project_name, project_name + '公告'])
                value['resolution']['procurementType'] = 'comparison'
        published = data.get("gongShiFaBuTimeShortText") if result else project.get(
            "xunJiaStartTimeText" if project.get("caiGouType") == 2 else "gongGaoStartTimeText")
        value.update(title=title, publishedAt=date_text(str(published or "")), content=visible)
        name = prefix + "-rendered.html"
        self.write(name, rendered.encode())
        value["resolution"].update(kind="eps_public_template_render", renderedFile=name, guid=guid,
                                    originalUrl=frame_url, networkMethod="GET", offlineReadResponse=True,
                                    renderedTitle=title, identityListTitles=labels,
                                    assets=list(self.asset_proof.values()), blockedRequests=self.render_blocked,
                                    visibleTextSha256=hashlib.sha256(visible.encode()).hexdigest())

    async def render_eps(self, frame_url: str, template: str, api_url: str, cached_reads: dict[str, bytes]) -> tuple[str, str]:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright

        if not self.browser:
            async def deny(_reader, writer):
                writer.close()
                await writer.wait_closed()
            self.proxy = await asyncio.start_server(deny, "127.0.0.1", 0)
            port = self.proxy.sockets[0].getsockname()[1]
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True, proxy={"server": f"http://127.0.0.1:{port}"},
                args=["--proxy-bypass-list=<-loopback>", "--disable-quic", "--disable-background-networking",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
        context = await self.browser.new_context(service_workers="block", accept_downloads=False)
        failures = []
        self.render_blocked = []
        read_count = 0

        async def route_request(route):
            nonlocal read_count
            req = route.request
            try:
                if req.url == frame_url and req.method == "GET":
                    await route.fulfill(status=200, content_type="text/html", body=template)
                elif req.url in cached_reads and req.method in {"GET", "POST"}:
                    # The template's read callback consumes a captured public GET;
                    # Chromium has no forwarding proxy and never sends this POST.
                    if req.url == api_url:
                        read_count += 1
                    await route.fulfill(status=200, content_type="application/json", body=cached_reads[req.url])
                elif req.resource_type in {"script", "stylesheet"} and req.method == "GET":
                    p = urlsplit(req.url)
                    if p.hostname != "eps.gdebidding.com" or not p.path.startswith("/gdjd-xunjia/"):
                        raise ValueError("eps_asset_scope_mismatch")
                    if req.url not in self.asset_cache:
                        r = (await self.network.fetch(req.url, respect_robots=True)).require_success()
                        self.asset_counter += 1
                        self.write(f"document-asset-{self.asset_counter:03d}.html", r.body)
                        self.asset_cache[req.url] = r
                        self.asset_proof[req.url] = {'url': r.url, 'file': f'document-asset-{self.asset_counter:03d}.html',
                                                    'sha256': hashlib.sha256(r.body).hexdigest()}
                    r = self.asset_cache[req.url]
                    await route.fulfill(status=r.status, body=r.body, headers={"content-type": r.headers.get("content-type", "text/plain")})
                elif (req.method == 'POST' and urlsplit(req.url).hostname == 'eps.gdebidding.com'
                      and urlsplit(req.url).path == '/gdjd-xunjia/common/nofilter/getLoginRemote.do'):
                    self.render_blocked.append({'method': 'POST', 'path': urlsplit(req.url).path, 'reason': 'anonymous_no_login'})
                    await route.abort()
                elif req.resource_type in {"image", "font", "media"} or (
                    req.is_navigation_request() and "crossDomainForFeiZhaoBiao" in req.url
                ):
                    await route.abort()
                else:
                    raise ValueError("eps_uncached_data_request:" + req.method + ":" + urlsplit(req.url).path)
            except (ValueError, SourceNetworkError) as exc:
                failures.append(str(exc))
                await route.abort()

        async def block_socket(socket):
            failures.append("eps_websocket_denied")
            await socket.close()

        await context.route("**/*", route_request)
        await context.route_web_socket("**/*", block_socket)
        try:
            page = await context.new_page()
            await page.goto(frame_url, wait_until="networkidle", timeout=30_000)
            await page.wait_for_function("document.querySelector('.detail_t')?.innerText.trim().length > 10", timeout=10_000)
            if failures or read_count != 1:
                raise ValueError(failures[0] if failures else "eps_read_response_count_mismatch")
            body = page.locator(".page_contect")
            visible = await body.inner_text()
            # Textarea values are not part of innerText but are visible notice data.
            remarks = await body.locator("textarea").evaluate_all(
                "nodes => nodes.filter(n => n.offsetParent !== null).map(n => n.value).join('\\n')")
            visible = visible.strip() + ("\n" + remarks.strip() if remarks.strip() else "")
            return visible, await page.content()
        except PlaywrightError as exc:
            raise ValueError('eps_render_incomplete') from exc
        finally:
            await context.close()
