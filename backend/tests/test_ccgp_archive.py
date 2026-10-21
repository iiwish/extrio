from datetime import date
from pathlib import Path

import pytest
from test_runtime import runtime_spec

from extrio.contracts import ContractBundle
from extrio.harvest import build_gather_spec
from extrio.public_pagination import ccgp_search_hosts, ccgp_window_truncated
from extrio.runtime import CrawleeRuntime, _as_date
from extrio.store import DEFAULT_COLLECTION_POLICY

SEARCH = 'http://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&timeType=4&searchchannel=0&dbselect=bidx&bidSort=1&pinMu=0'


@pytest.mark.parametrize('suffix', ['', '&page_index=2', '&bidSort=2', '&redirect=http://evil.test'])
def test_ccgp_search_host_scope_is_fixed(suffix):
    assert ccgp_search_hosts(SEARCH + suffix) == ({'search.ccgp.gov.cn', 'www.ccgp.gov.cn'} if not suffix else set())


def test_recent_column_exhaustion_cannot_certify_a_month():
    html = 'Pager({size:25, current:24, prefix: "index"}); http://search.ccgp.gov.cn/bxsearch'
    assert ccgp_window_truncated('http://www.ccgp.gov.cn/cggg/zygg/index_24.htm', html, '2026-10-19', '2026-09-19')
    assert not ccgp_window_truncated('https://other.test/list', html, '2026-10-19', '2026-09-19')
    assert not ccgp_window_truncated('http://www.ccgp.gov.cn/cggg/zygg/index_24.htm', html, '2026-09-18', '2026-09-19')


def test_archive_compilation_uses_application_owned_host_scope():
    contracts = ContractBundle(Path(__file__).resolve().parents[2] / 'docs/contracts')
    source = {'id':'ccgp_archive','name':'Archive','intent':'Collect','sourceHost':'search.ccgp.gov.cn','sourceUrl':SEARCH}
    spec = build_gather_spec(source, contracts)
    assert spec['sourceContext']['allowedHosts'] == ['search.ccgp.gov.cn','www.ccgp.gov.cn']


async def test_native_runtime_cannot_checkpoint_a_recent_only_column(tmp_path, monkeypatch):
    entry='http://www.ccgp.gov.cn/cggg/zygg/index_24.htm'
    spec=runtime_spec(entry,mode='list_detail')
    spec['sourceContext']['allowedHosts']=['www.ccgp.gov.cn']
    collector={'id':'recent','name':'Recent','sourceHost':'www.ccgp.gov.cn','collectionVersion':'v1',
        'candidate':{'gatherSpec':spec},'collectionPolicy':{**DEFAULT_COLLECTION_POLICY,'id':'p','checkpointMode':'observed'}}
    runtime=CrawleeRuntime(tmp_path)

    async def fetch(urls,*_args):
        if urls==[entry]:
            return {entry:'<ul class="notice-list"><li><a class="notice-title" href="/detail/A">A</a>'
                '<time datetime="2026-10-19"></time></li></ul> http://search.ccgp.gov.cn/bxsearch'}
        return {url:'<h1 class="notice-title">A</h1><time datetime="2026-10-19"></time>' for url in urls}

    async def progress(*_args):
        pass

    monkeypatch.setattr(runtime,'_fetch_many',fetch)
    result=await runtime.run(collector,{'id':'recent1','ruleVersion':'v1','ruleDigest':'d','windowStart':'2026-09-19',
        'executionMode':'initial','coverageMode':'observed'},progress)
    assert result.pagination_stop_reason=='source_window_truncated'
    assert not result.coverage_complete and result.coverage_progress is None


@pytest.mark.parametrize(('value','expected'), [
    ('2026.10.19 16:52:00 | 采购人：公开单位', date(2026,10,19)),
    ('2026.13.40 16:52:00 | 采购人：公开单位', None),
    ('项目名称2026.10.19', None),
])
def test_official_search_list_date_is_strictly_bounded(value, expected):
    assert _as_date(value) == expected


@pytest.mark.parametrize(('page', 'response', 'reason'), [
    (1, '<title>频繁访问!中国政府采购网</title><p>您的访问过于频繁,请稍后再试。</p>', 'source_rate_limited'),
    (2, '<title>频繁访问!中国政府采购网</title><p>您的访问过于频繁,请稍后再试。</p>', 'source_rate_limited'),
    (2, '<html><title>Temporary gateway</title><body>Try later</body></html>', 'source_structure_mismatch'),
])
@pytest.mark.parametrize('has_prior', [False, True])
async def test_invalid_list_responses_stop_requests_and_keep_prior_coverage(tmp_path, monkeypatch, page, response, reason, has_prior):
    spec = runtime_spec(SEARCH, mode='list_detail')
    spec['sourceContext']['allowedHosts'] = ['search.ccgp.gov.cn', 'www.ccgp.gov.cn']
    spec['collect']['list']['pagination'] = {'type': 'page', 'parameter': 'page_index', 'start': 1, 'step': 1, 'maxPages': 3}
    spec['collect']['budget']['maxPages'] = 3
    collector = {'id': 'guarded', 'name': 'Guarded', 'sourceHost': 'search.ccgp.gov.cn', 'collectionVersion': 'v1',
        'candidate': {'gatherSpec': spec}, 'collectionPolicy': {**DEFAULT_COLLECTION_POLICY, 'id': 'p',
            'maxPages': 3, 'maxItems': 50, 'checkpointMode': 'observed'}}
    prior = {'ruleDigest': 'd', 'policyVersionId': 'p', 'windowStart': '2026-09-19', 'resumeUrl': SEARCH,
        'pageIndex': 0, 'anchorUrl': 'http://www.ccgp.gov.cn/detail/A', 'processedUrls': ['http://www.ccgp.gov.cn/detail/A'],
        'olderPagesBefore': 0, 'watermark': '2026-10-19'}
    calls = []

    async def fetch(urls, *_args):
        calls.extend(urls)
        assert len(urls) == 1 and '/bxsearch?' in urls[0], 'No detail or retry request after invalid list'
        if len(calls) == page:
            return {urls[0]: response}
        return {urls[0]: '<ul class="notice-list"><li><a class="notice-title" href="http://www.ccgp.gov.cn/detail/A">A</a>'
                '<time datetime="2026-10-19"></time></li><li><a class="notice-title" href="http://www.ccgp.gov.cn/detail/B">B</a>'
                '<time datetime="2026-10-19"></time></li></ul>'}

    async def quiet(*_args):
        pass

    runtime = CrawleeRuntime(tmp_path)
    monkeypatch.setattr(runtime, '_fetch_many', fetch)
    result = await runtime.run(collector, {'id': 'invalid-list', 'ruleVersion': 'v1', 'ruleDigest': 'd',
        'windowStart': '2026-09-19', 'executionMode': 'initial', 'coverageMode': 'observed',
        'coverageProgressBefore': prior if has_prior else None}, quiet)
    assert result.pagination_stop_reason == reason
    assert not result.coverage_complete and result.coverage_progress == (prior if has_prior else None)
    assert not result.items and result.metrics['detailPagesFetched'] == 0
    assert len(calls) == page and result.metrics['listPagesFetched'] == page
    assert result.evidence_digest
    assert (tmp_path / 'invalid-list/attempt_1' / f'list-{page:03d}.html').read_text() == response
