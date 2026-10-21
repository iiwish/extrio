"""Verified anonymous publisher endpoints for otherwise non-navigable JS pagers."""

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup


def ccgp_search_hosts(url: str) -> set[str]:
    p = urlsplit(url)
    query = parse_qs(p.query)
    fixed = {'searchtype': ['1'], 'timeType': ['4'], 'searchchannel': ['0'], 'dbselect': ['bidx'], 'bidSort': ['1'], 'pinMu': ['0']}
    if (p.scheme not in {'http', 'https'} or p.hostname != 'search.ccgp.gov.cn' or p.path != '/bxsearch'
            or p.username or p.password or p.port not in {None, 80 if p.scheme == 'http' else 443}
            or set(query) != {*fixed, 'page_index'} or any(query.get(k) != v for k, v in fixed.items())
            or len(query['page_index']) != 1 or not re.fullmatch('[1-9][0-9]{0,5}', query['page_index'][0])):
        return set()
    return {'search.ccgp.gov.cn', 'www.ccgp.gov.cn'}


def ccgp_window_truncated(url: str, html: str, oldest: str, window_start: str) -> bool:
    p = urlsplit(url)
    return bool(p.hostname == 'www.ccgp.gov.cn' and re.fullmatch(r'/cggg/zygg/index_24\.htm', p.path)
                and 'search.ccgp.gov.cn/bxsearch' in html and oldest >= window_start)


def public_list_response_issue(url: str, response: str) -> str | None:
    if urlsplit(url).hostname not in {'search.ccgp.gov.cn', 'www.ccgp.gov.cn'}:
        return None
    soup = BeautifulSoup(response, 'html.parser')
    title = soup.title.get_text(strip=True) if soup.title else ''
    if title.startswith(('频繁访问', '访问过于频繁')) or (
            '您的访问过于频繁' in soup.get_text() and not soup.select_one('ul.vT-srch-result-list-bid')):
        return 'source_rate_limited'
    return None


def verified_empty_public_list(url: str, response: str) -> bool:
    parts = urlsplit(url)
    if (parts.hostname != 'www.zy91.com' or parts.path != '/content/get_article'
            or parse_qs(parts.query).get('cid') != ['193']):
        return False
    validate_hospital_list(url, response)
    return json.loads(response)['data']['list'] == []


def hospital_paging_script(html: str, url: str) -> str | None:
    parts = urlsplit(url)
    if parts.hostname != 'www.zy91.com' or parts.path != '/general/list' or parse_qs(parts.query).get('cid') != ['193']:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    config = re.compile(r"pagedata\(\s*'\d+'\s*,\s*'193'\s*,\s*'pageBox'\s*,\s*'list'\s*,\s*'articles'\s*,\s*10\s*\)")
    if not any(config.search(node.get_text()) for node in soup.select('script:not([src])')):
        return None
    target = urljoin(url, '/public/cn/js/pagedata.js')
    return target if any(urljoin(url, node['src']) == target for node in soup.select('script[src]')) else None


def hospital_list_request(html: str, url: str, script: str) -> str | None:
    if not hospital_paging_script(html, url):
        return None
    # Recognize the publisher's literal GET wiring, never execute remote JavaScript.
    wiring = r"url:\s*'/content/get_article'\s*,\s*data:\s*\{page:page,cid:cid,cur:pagesize\}\s*,\s*method:\s*'get'"
    if not re.search(wiring, script) or "'/content/default/'" not in script:
        return None
    return urljoin(url, '/content/get_article?page=1&cid=193&cur=10')


def validate_hospital_list(url: str, response: str) -> None:
    parts = urlsplit(url)
    if parts.hostname != 'www.zy91.com' or parts.path != '/content/get_article':
        return
    data = json.loads(response)
    rows = data.get('data', {}).get('list')
    if data.get('code') != 1 or not isinstance(rows, list):
        raise ValueError('hospital_public_list_invalid_response')
    for row in rows:
        if (not isinstance(row, dict) or str(row.get('category_id')) != '193'
                or not re.fullmatch(r'[0-9]+', str(row.get('id', '')))):
            raise ValueError('hospital_public_list_invalid_identity')
