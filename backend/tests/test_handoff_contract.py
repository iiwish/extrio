import copy
from types import SimpleNamespace

import pytest

import extrio.app as app_module
from extrio.adaptive_compile import CURRENT_SESSION
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer, _sample_issues
from extrio.model_gateway import ActiveModel, ModelCompileError, ModelRuleCompiler, normalize_discovery_plan, normalize_rule_plan
from extrio.store import Store

FIELDS = [
    {'key': 'title', 'label': 'title', 'description': '', 'type': 'string', 'required': True, 'identity': True, 'fingerprint': True},
    {'key': 'detail_url', 'label': 'URL', 'description': '', 'type': 'url', 'required': True, 'identity': True, 'fingerprint': False},
]
DISCOVERY = {'mode': 'list_detail', 'transport': 'http', 'list': {
    'itemsSelector': 'css:li', 'pagination': {'type': 'none'}, 'fields': {
        'title': {'selector': 'css:a::text'},
        'detailUrl': {'selector': 'css:a::attr(href)', 'valueType': 'url'},
    }}}
RAW = {'detail': {'fields': {'title': {'selector': 'css:h1::text'},
                           'detailUrl': {'selector': 'css:link[rel=canonical]::attr(href)', 'valueType': 'url'}}},
       'bindings': {'detailUrl': 'list.detailUrl', 'title': 'detail.title'},
       'identityFields': ['title', 'detail_url']}


def test_business_url_mapping_does_not_rename_fixed_handoff():
    discovery = normalize_discovery_plan(DISCOVERY)
    original = copy.deepcopy(discovery)
    plan = normalize_rule_plan(RAW, discovery, expected_fields=FIELDS)
    assert plan['list'] == original['list']
    assert discovery == original
    assert 'detail_url' in plan['detail']['fields']
    assert plan['bindings']['detailUrl'] == 'list.detailUrl'


@pytest.mark.asyncio
@pytest.mark.parametrize('self_link', [False, True])
async def test_worker_compilation_context_validates_frozen_url_output(tmp_path, monkeypatch, self_link):
    store = Store(tmp_path / 'test.db')
    store.initialize()
    collector = store.create_collector('Source', 'Read notices', 'https://example.com/list', 'example.com')
    collection = store.get_collection(collector['collectionId'])
    store.collection_command('PATCH', collection['id'], {'revision': collection['revision'], 'fieldDraft': {'fields': FIELDS}},
                             'draft', audit=None)
    version = store.publish_collection_version(collection['id'], collection['revision'] + 1, 'test')
    context = store.collector_compilation_context({**collector, 'collectionVersion': version['id']})
    assert context['expectedFields'] == FIELDS
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / 'key'))
    monkeypatch.setattr(compiler, '_model', lambda: ActiveModel('custom', 'https://fixture.invalid', 'fixture', ''))
    calls = []

    async def complete(_model, _system, evidence, **_kwargs):
        calls.append(evidence)
        assert evidence['expectedFields'] == FIELDS
        raw = copy.deepcopy(RAW)
        if not self_link:
            raw['detail']['fields'].pop('detailUrl')
        return raw

    monkeypatch.setattr(compiler, '_complete_json', complete)
    listing = '<ul><li><a href="/1">One</a></li><li><a href="/2">Two</a></li></ul>'
    samples = [(f'https://example.com/{i}',
                (f'<link rel="canonical" href="https://example.com/{i}">' if self_link else '') + f'<h1>{title}</h1>')
               for i, title in ((1, 'One'), (2, 'Two'))]
    plan = await compiler.compile(context, context['sourceUrl'], listing, samples, normalize_discovery_plan(DISCOVERY))
    explorer = Crawl4AIExplorer(app_module.contracts, tmp_path / 'artifacts', compiler)
    result = explorer._validate_candidate(context, context, 'op_test', context['sourceUrl'], listing, samples, plan, None, {})
    assert len(calls) == 1
    assert len(result.preview_items) == 2
    assert all(item['decision'] == 'accepted' for item in result.preview_items)
    assert [item['extractedData']['detail_url'] for item in result.preview_items] == [url for url, _ in samples]
    assert result.candidate['gatherSpec']['contract']['outputContractDigest'] == version['outputContractDigest']
    assert _sample_issues(result.candidate, result.preview_items) == []

    snapshots = {context['sourceUrl']: listing, **dict(samples)}

    class Browser:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def arun(self, *, url, **_kwargs):
            assert url in snapshots
            return SimpleNamespace(html=snapshots[url], redirected_url=url)

    async def full_complete(_model, _system, evidence, **kwargs):
        session = CURRENT_SESSION.get()
        session.budget.settle(session.current_reservation, 100, 100)
        if kwargs['purpose'] == 'discover':
            return {'action': 'propose_rule', 'rule': copy.deepcopy(DISCOVERY)}
        return {'action': 'propose_rule', 'rule': await complete(_model, _system, evidence)}

    monkeypatch.setattr('extrio.explorer.RestrictedBrowser', Browser)
    monkeypatch.setattr(compiler, '_complete_json', full_complete)
    diagnostics = []

    async def progress(*_args):
        pass

    async def diagnostic(value):
        diagnostics.append(value)

    full_result = await explorer.explore(context, 'op_full', progress, diagnostic=diagnostic)
    assert len(full_result.preview_items) == 2
    assert diagnostics[-1]['validated'] is True
    assert diagnostics[-1]['budget']['calls'] == 2

    with pytest.raises(ModelCompileError) as error:
        explorer._validate_candidate(context, context, 'op_missing_handoff', context['sourceUrl'], listing,
                                     [('https://example.com/not-in-list', samples[0][1])], plan, None, {})
    assert error.value.issues == [{'code': 'DETAIL_URL_MISMATCH', 'sample': 1, 'field': 'detailUrl', 'stage': 'list'}]


def test_declared_business_detail_url_still_requires_matching_value():
    candidate = {'fields': [], 'gatherSpec': {'contract': {
        'fieldBindings': {'detailUrl': 'list.detailUrl'},
        'normalizedItemSchema': {'properties': {'detailUrl': {'type': 'string'}}},
    }}}
    item = {'decision': 'accepted', 'extractedData': {'detailUrl': 'https://example.com/wrong'},
            'sourceUrl': 'https://example.com/right', 'entityKey': 'entity'}
    assert _sample_issues(candidate, [item]) == [{'code': 'DETAIL_URL_MISMATCH', 'sample': 1, 'field': 'detailUrl'}]


@pytest.mark.asyncio
async def test_invalid_fixed_discovery_stops_before_model_call(tmp_path, monkeypatch):
    compiler = ModelRuleCompiler(Store(tmp_path / 'test.db'), CredentialCipher(tmp_path / 'key'))
    monkeypatch.setattr(compiler, '_model', lambda: ActiveModel('custom', 'https://fixture.invalid', 'fixture', ''))
    calls = []

    async def complete(*_args, **_kwargs):
        calls.append(True)
        return copy.deepcopy(RAW)

    monkeypatch.setattr(compiler, '_complete_json', complete)
    broken = copy.deepcopy(DISCOVERY)
    broken['list']['fields'].pop('detailUrl')
    with pytest.raises(RuntimeError) as error:
        await compiler.compile({}, 'https://example.com/list', '', [], broken)
    assert not calls
    assert error.value.code == 'MODEL_COMPILATION_CONTEXT_INVALID'
    assert error.value.retryable is False
