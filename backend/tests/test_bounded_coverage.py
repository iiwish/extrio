import copy

import pytest
from test_runtime import fixture_server, runtime_spec

from extrio.collection_fields import constrain_rule_plan
from extrio.runtime import CrawleeRuntime
from extrio.store import DEFAULT_COLLECTION_POLICY, Store


def test_frozen_contract_preserves_only_bound_operational_list_date():
    plan = {'mode': 'list_detail', 'list': {'fields': {
        'title': {'selector': 'css:a::text'}, 'detailUrl': {'selector': 'css:a::attr(href)'},
        'date': {'selector': 'css:time::text'}, 'noise': {'selector': 'css:body::text'}}},
        'detail': {'fields': {'title': {'selector': 'css:h1::text'}}},
        'bindings': {'title': 'detail.title', 'listPublishedAt': 'list.date', 'detailUrl': 'list.detailUrl'}}
    version = {'fields': [{'key': 'title', 'label': 'Title', 'type': 'string', 'required': True}],
               'identityFields': ['title'], 'fingerprintFields': ['title']}
    result = constrain_rule_plan(plan, version)
    assert result['bindings']['listPublishedAt'] == 'list.listPublishedAt'
    assert result['list']['fields']['listPublishedAt']['selector'] == 'css:time::text'
    assert not result['list']['fields']['listPublishedAt']['required']
    assert 'noise' not in result['list']['fields']
    assert result['identityFields'] == result['fingerprintFields'] == ['title']


def test_observed_policy_is_explicit_and_invalidates_continuation(tmp_path):
    store = Store(tmp_path / 'policy.db')
    store.initialize()
    collector = store.create_collector('Source', 'Goal', 'https://example.com/list', 'example.com')
    collector['coverageProgress'] = {'ruleDigest': 'old'}
    store.save_collector(collector)
    updated = store.create_collection_policy(collector['id'], {**DEFAULT_COLLECTION_POLICY, 'checkpointMode': 'observed'})
    assert updated['collectionPolicy']['checkpointMode'] == 'observed'
    assert updated.get('coverageProgress') is None
    with pytest.raises(ValueError):
        store.create_collection_policy(collector['id'], {**DEFAULT_COLLECTION_POLICY, 'checkpointMode': 'anything'})


async def quiet(*_args):
    pass


@pytest.mark.parametrize('limit', ['pages', 'items'])
async def test_caps_resume_with_overlap_and_do_not_count_an_old_page_twice(tmp_path, limit):
    with fixture_server() as root:
        spec = runtime_spec(root + '/window-list', mode='list_detail')
        spec['collect']['list']['pagination']['maxPages'] = spec['collect']['budget']['maxPages'] = 3
        spec['collect']['budget']['maxItems'] = 50
        collector = {'id': 'coverage', 'name': 'Coverage', 'sourceHost': '127.0.0.1', 'collectionVersion': 'v1',
                     'candidate': {'gatherSpec': spec}, 'collectionPolicy': {
                         **DEFAULT_COLLECTION_POLICY, 'id': 'policy1', 'maxPages': 2 if limit == 'pages' else 3,
                         'maxItems': 1 if limit == 'items' else 50, 'checkpointMode': 'observed'}}
        run = {'id': 'run1', 'ruleVersion': 'v1', 'ruleDigest': 'digest1', 'windowStart': '2026-08-01',
               'executionMode': 'initial', 'coverageMode': 'observed'}
        runtime = CrawleeRuntime(tmp_path)
        first = await runtime.run(collector, run, quiet)
        assert not first.coverage_complete and first.coverage_progress
        current = first
        for index in range(2, 6):
            next_run = {**run, 'id': f'run{index}', 'coverageProgressBefore': current.coverage_progress}
            current = await runtime.run(collector, next_run, quiet)
            assert current.metrics['listPagesFetched'] <= collector['collectionPolicy']['maxPages']
            assert len(current.items) <= collector['collectionPolicy']['maxItems']
            if current.coverage_complete:
                break
        assert current.coverage_complete
        assert current.watermark_candidate == '2026-08-30'
        assert current.pagination_stop_reason == 'time_window_reached'


async def test_resume_context_cannot_cross_rules(tmp_path):
    with fixture_server() as root:
        spec = runtime_spec(root + '/window-list', mode='list_detail')
        collector = {'id': 'coverage', 'name': 'Coverage', 'sourceHost': '127.0.0.1', 'collectionVersion': 'v1',
                     'candidate': {'gatherSpec': spec}, 'collectionPolicy': {
                         **DEFAULT_COLLECTION_POLICY, 'id': 'p1', 'maxPages': 2, 'checkpointMode': 'observed'}}
        run = {'id': 'run_context', 'ruleVersion': 'v2', 'ruleDigest': 'new', 'windowStart': '2026-08-01',
               'executionMode': 'initial', 'coverageMode': 'observed', 'coverageProgressBefore': {
                   'ruleDigest': 'old', 'policyVersionId': 'p1', 'windowStart': '2026-08-01',
                   'resumeUrl': root + '/window-list?page=999'}}
        result = await CrawleeRuntime(tmp_path).run(collector, run, quiet)
        assert result.metrics['listPagesFetched'] == 2
        assert result.coverage_progress['ruleDigest'] == 'new'
        assert result.coverage_progress['resumeUrl'].endswith('page=2')


async def test_unknown_list_date_cannot_certify_observed_coverage(tmp_path):
    with fixture_server() as root:
        spec = runtime_spec(root + '/list', mode='list_detail')
        spec = copy.deepcopy(spec)
        spec['collect']['list']['fields']['listPublishedAt']['selector'] = 'css:.missing::text'
        spec['collect']['list']['fields']['listPublishedAt']['required'] = False
        collector = {'id': 'coverage', 'name': 'Coverage', 'sourceHost': '127.0.0.1', 'collectionVersion': 'v1',
                     'candidate': {'gatherSpec': spec}, 'collectionPolicy': {**DEFAULT_COLLECTION_POLICY,
                         'id': 'p1', 'checkpointMode': 'observed'}}
        result = await CrawleeRuntime(tmp_path).run(collector, {'id': 'unknown', 'ruleVersion': 'v1',
            'ruleDigest': 'd', 'windowStart': '2026-08-01', 'executionMode': 'initial', 'coverageMode': 'observed'}, quiet)
        assert not result.coverage_complete and result.coverage_progress is None
        assert result.pagination_stop_reason == 'coverage_date_unknown'


async def test_missing_resume_anchor_restarts_without_certifying_a_gap(tmp_path):
    with fixture_server() as root:
        spec = runtime_spec(root + '/window-list', mode='list_detail')
        collector = {'id': 'coverage', 'name': 'Coverage', 'sourceHost': '127.0.0.1', 'collectionVersion': 'v1',
                     'candidate': {'gatherSpec': spec}, 'collectionPolicy': {**DEFAULT_COLLECTION_POLICY,
                         'id': 'p1', 'maxPages': 2, 'checkpointMode': 'observed'}}
        run = {'id': 'anchor1', 'ruleVersion': 'v1', 'ruleDigest': 'd', 'windowStart': '2026-08-01',
               'executionMode': 'initial', 'coverageMode': 'observed'}
        runtime = CrawleeRuntime(tmp_path)
        first = await runtime.run(collector, run, quiet)
        shifted = {**first.coverage_progress, 'anchorUrl': root + '/removed', 'overlapUrls': []}
        result = await runtime.run(collector, {**run, 'id': 'anchor2', 'coverageProgressBefore': shifted}, quiet)
        assert result.metrics['listPagesFetched'] == 2 and result.metrics['warningCount'] >= 1
        assert not result.coverage_complete and result.coverage_progress is None
        assert result.pagination_stop_reason == 'coverage_order_unverified'


async def test_cross_page_date_reordering_cannot_certify_coverage(tmp_path, monkeypatch):
    with fixture_server() as root:
        spec = runtime_spec(root + '/window-list', mode='list_detail')
        collector = {'id': 'coverage', 'name': 'Coverage', 'sourceHost': '127.0.0.1', 'collectionVersion': 'v1',
                     'candidate': {'gatherSpec': spec}, 'collectionPolicy': {**DEFAULT_COLLECTION_POLICY,
                         'id': 'p1', 'maxPages': 2, 'checkpointMode': 'observed'}}
        runtime = CrawleeRuntime(tmp_path)
        fetch = runtime._fetch_many

        async def reordered(urls, *args):
            pages = await fetch(urls, *args)
            if 'page=2' in urls[0]:
                pages[urls[0]] = pages[urls[0]].replace('2026-07-02', '2026-08-31')
            return pages

        monkeypatch.setattr(runtime, '_fetch_many', reordered)
        result = await runtime.run(collector, {'id': 'order1', 'ruleVersion': 'v1', 'ruleDigest': 'd',
            'windowStart': '2026-08-01', 'executionMode': 'initial', 'coverageMode': 'observed'}, quiet)
        assert result.pagination_stop_reason == 'coverage_order_unverified'
        assert not result.coverage_complete and result.coverage_progress is None


async def test_a_repeated_next_link_is_not_exhausted_coverage(tmp_path, monkeypatch):
    with fixture_server() as root:
        spec = runtime_spec(root + '/window-list', mode='list_detail')
        collector = {'id': 'coverage', 'name': 'Coverage', 'sourceHost': '127.0.0.1', 'collectionVersion': 'v1',
                     'candidate': {'gatherSpec': spec}, 'collectionPolicy': {**DEFAULT_COLLECTION_POLICY,
                         'id': 'p1', 'maxPages': 3, 'checkpointMode': 'observed'}}
        runtime = CrawleeRuntime(tmp_path)
        fetch = runtime._fetch_many

        async def repeated(urls, *args):
            pages = await fetch(urls, *args)
            if urls == [root + '/window-list']:
                pages[urls[0]] = pages[urls[0]].replace('/window-list?page=2', '/window-list')
            return pages

        monkeypatch.setattr(runtime, '_fetch_many', repeated)
        result = await runtime.run(collector, {'id': 'loop1', 'ruleVersion': 'v1', 'ruleDigest': 'd',
            'windowStart': '2026-08-01', 'executionMode': 'initial', 'coverageMode': 'observed'}, quiet)
        assert result.pagination_stop_reason == 'coverage_order_unverified'
        assert not result.coverage_complete and result.coverage_progress is None


async def test_query_pager_repeating_a_page_does_not_advance_coverage(tmp_path, monkeypatch):
    with fixture_server() as root:
        spec = runtime_spec(root + '/window-list', mode='list_detail')
        spec['collect']['list']['pagination'] = {'type':'page','parameter':'page','start':1,'step':1,'maxPages':3}
        collector = {'id':'coverage','name':'Coverage','sourceHost':'127.0.0.1','collectionVersion':'v1',
                     'candidate':{'gatherSpec':spec},'collectionPolicy':{**DEFAULT_COLLECTION_POLICY,
                         'id':'p1','maxPages':3,'checkpointMode':'observed'}}
        runtime = CrawleeRuntime(tmp_path)
        fetch = runtime._fetch_many
        first = None

        async def repeated(urls, *args):
            nonlocal first
            if '/window-list' in urls[0]:
                if first is None:
                    first = (await fetch(urls, *args))[urls[0]].replace('2026-08-29','2026-08-30')
                return {urls[0]:first}
            return await fetch(urls, *args)

        monkeypatch.setattr(runtime, '_fetch_many', repeated)
        result = await runtime.run(collector, {'id':'query-loop','ruleVersion':'v1','ruleDigest':'d',
            'windowStart':'2026-08-01','executionMode':'initial','coverageMode':'observed'}, quiet)
        assert result.pagination_stop_reason == 'coverage_order_unverified'
        assert not result.coverage_complete and result.coverage_progress is None


async def test_moving_offset_anchor_can_be_found_on_the_next_budgeted_page(tmp_path, monkeypatch):
    with fixture_server() as root:
        spec=runtime_spec(root+'/window-list',mode='list_detail')
        spec['collect']['budget']['maxPages']=3
        spec['collect']['list']['pagination']={'type':'page','parameter':'page','start':1,'step':1,'maxPages':3}
        collector={'id':'coverage','name':'Coverage','sourceHost':'127.0.0.1','collectionVersion':'v1',
            'candidate':{'gatherSpec':spec},'collectionPolicy':{**DEFAULT_COLLECTION_POLICY,'id':'p1',
                'maxPages':3,'checkpointMode':'observed'}}
        runtime=CrawleeRuntime(tmp_path)
        shifted=False

        async def fetch(urls,*_args):
            from urllib.parse import parse_qs, urlsplit

            pages={}
            for url in urls:
                if '/window-list' in url:
                    n=int(parse_qs(urlsplit(url).query).get('page',['1'])[0])
                    rows=({1:['A','B'],2:['C','D'],3:['D','E'],4:['F','G'],5:['old']} if shifted else
                          {1:['A','B'],2:['C','D'],3:['E','F']})[n]
                    pages[url]='<ul class="notice-list">'+''.join(
                        f'<li><a class="notice-title" href="/detail/{code}">{code}</a>'
                        f'<time datetime="{"2026-07-01" if code=="old" else "2026-08-30"}"></time></li>' for code in rows)+'</ul>'
                else:
                    code=url.rsplit('/',1)[-1]
                    pages[url]=f'<h1 class="notice-title">{code}</h1><div class="meta"><time datetime="2026-08-30"></time></div>'
            return pages

        monkeypatch.setattr(runtime,'_fetch_many',fetch)
        run={'id':'offset1','ruleVersion':'v1','ruleDigest':'d','windowStart':'2026-08-01','executionMode':'initial','coverageMode':'observed'}
        first=await runtime.run(collector,run,quiet)
        assert first.coverage_progress['anchorUrl']==root+'/detail/F'
        shifted=True
        result=await runtime.run(collector,{**run,'id':'offset2','coverageProgressBefore':first.coverage_progress},quiet)
        assert result.metrics['listPagesFetched']==3
        assert result.coverage_progress['pageIndex']==4
        assert any(i['title']=='G' for i in result.items)


@pytest.mark.parametrize('complete_page', [True, False])
async def test_removed_tail_anchor_requires_a_complete_page_and_two_tail_witnesses(tmp_path, monkeypatch, complete_page):
    with fixture_server() as root:
        spec=runtime_spec(root+'/window-list',mode='list_detail')
        spec['collect']['budget']['maxPages']=3
        spec['collect']['list']['pagination']={'type':'page','parameter':'page','start':1,'step':1,'maxPages':3}
        collector={'id':'coverage','name':'Coverage','sourceHost':'127.0.0.1','collectionVersion':'v1',
            'candidate':{'gatherSpec':spec},'collectionPolicy':{**DEFAULT_COLLECTION_POLICY,'id':'p1',
                'maxPages':3,'checkpointMode':'observed'}}
        runtime=CrawleeRuntime(tmp_path)

        async def fetch(urls,*_args):
            from urllib.parse import parse_qs, urlsplit

            pages={}
            for url in urls:
                if '/window-list' in url:
                    n=int(parse_qs(urlsplit(url).query).get('page',['1'])[0])
                    rows={3:['E','F','G'],4:['old-a'],5:['old-b']}[n]
                    pages[url]='<ul class="notice-list">'+''.join(
                        f'<li><a class="notice-title" href="/detail/{code}">{code}</a>'
                        f'<time datetime="{"2026-07-01" if code.startswith("old") else "2026-08-30"}"></time></li>'
                        for code in rows)+'</ul>'
                else:
                    code=url.rsplit('/',1)[-1]
                    pages[url]=f'<h1 class="notice-title">{code}</h1><div class="meta"><time datetime="2026-08-30"></time></div>'
            return pages

        monkeypatch.setattr(runtime,'_fetch_many',fetch)
        prior={'ruleDigest':'d','policyVersionId':'p1','windowStart':'2026-08-01','resumeUrl':root+'/window-list?page=3',
            'pageIndex':2,'anchorUrl':root+'/detail/H','processedUrls':[root+'/detail/'+c for c in ['E','F','H']],
            'olderPagesBefore':0,'watermark':'2026-08-30','pageComplete':complete_page,
            'overlapUrls':[root+'/detail/'+c for c in ['E','F','H']]}
        result=await runtime.run(collector,{'id':'tail-change','ruleVersion':'v1','ruleDigest':'d','windowStart':'2026-08-01',
            'executionMode':'initial','coverageMode':'observed','coverageProgressBefore':prior},quiet)
        assert result.coverage_complete==complete_page
        if not complete_page:
            assert result.pagination_stop_reason=='coverage_order_unverified' and result.coverage_progress is None
