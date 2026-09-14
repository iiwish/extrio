"""Run the entire explorer loop on saved snapshots and the Worker contract without network/model access."""
import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from extrio.adaptive_compile import CURRENT_SESSION
from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer
from extrio.harvest import discover_records_from_spec
from extrio.model_budget import BudgetError
from extrio.model_gateway import ActiveModel, ModelRuleCompiler
from extrio.pagination import pagination_hints
from extrio.store import Store

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PAGINATION = 'pagination' in sys.argv[1:]


async def main():
    settings = get_settings()
    store = Store(settings.database_path)
    collector = store.get_collector('collector_ggzyfw_beijing_gov_cn_53130add')
    context = store.collector_compilation_context(collector)
    snapshots = settings.artifact_path / ('op_af66f32a1fee4c71' if PAGINATION else 'op_x_433fa9d739e941')
    discovery = json.loads((snapshots / 'discovery-plan.json').read_text())
    listing = (snapshots / 'list-001.html').read_text()
    records, _ = discover_records_from_spec(listing, context['sourceUrl'], discovery['list'])
    urls = list(dict.fromkeys(row['detailUrl'] for row in records))[:3]
    pages = {context['sourceUrl']: listing,
             **{url: (snapshots / f'detail-{i:03d}.html').read_text() for i, url in enumerate(urls, 1)}}
    fixture = {'detail': {'fields': {
        'title': {'selector': 'css:meta[http-equiv="ArticleTitle"]::attr(content)'},
        'content': {'selector': 'css:div.div-content::html', 'valueType': 'html', 'required': False},
        'publish_date': {'selector': 'css:meta[http-equiv="PubDate"]::attr(content)', 'required': False,
                         'transforms': [{'type': 'regex_extract', 'pattern': '[0-9]{4}-[0-9]{2}-[0-9]{2}', 'group': 0}]},
    }}, 'bindings': {'detailUrl': 'list.detailUrl', 'title': 'detail.title', 'content': 'detail.content'}}

    class Browser:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def arun(self, *, url, **_kwargs):
            assert url in pages, 'offline replay cannot fetch other pages'
            return SimpleNamespace(html=pages[url], redirected_url=url)

    results = []
    for broken in (False, True):
        compiler = ModelRuleCompiler(store, CredentialCipher(settings.credential_encryption_key_path))
        compiler._model = lambda: ActiveModel('custom', 'https://offline.invalid', 'deterministic-fixture', '')
        diagnostics = []
        phases = []

        async def complete(_model, _system, evidence, **kwargs):
            session = CURRENT_SESSION.get()
            session.budget.settle(session.current_reservation, 100, 100)
            if kwargs['purpose'] == 'discover':
                proposal = copy.deepcopy(discovery)
                if PAGINATION and session.budget.calls > 1:
                    assert evidence['validationFeedback'][0]['code'] == 'PAGINATION_NEXT_LINK_MISSING'
                    hints = pagination_hints(listing, context['sourceUrl'])
                    assert hints and hints[0]['targetUrl'].endswith('/index_2.html')
                    proposal['list']['pagination']['selector'] = hints[0]['selector']
                return {'action': 'propose_rule', 'rule': proposal}
            assert evidence['expectedFields'] == context['expectedFields']
            proposal = copy.deepcopy(fixture)
            proposal['rationale'] = f'Proposal revision {session.budget.calls}'
            if broken:
                proposal['detail']['fields']['content']['selector'] = f'css:.missing-{session.budget.calls}::html'
            return {'action': 'propose_rule', 'rule': proposal}

        async def diagnostic(summary):
            diagnostics.append(summary)

        async def progress(stage, _percent, _metrics):
            phases.append(stage)

        compiler._complete_json = complete
        explorer = Crawl4AIExplorer(ContractBundle(ROOT / 'docs/contracts'), Path('/tmp/extrio-full-loop-replay'), compiler)
        with patch('extrio.explorer.RestrictedBrowser', Browser):
            try:
                result = await explorer.explore(context, 'broken' if broken else 'valid', progress, diagnostic=diagnostic)
                assert not broken
                assert len(result.preview_items) == 3 and all(item['decision'] == 'accepted' for item in result.preview_items)
                assert [item['extractedData']['detail_url'] for item in result.preview_items] == urls
                assert all(set(item['extractedData']) == {f['key'] for f in context['expectedFields']} for item in result.preview_items)
                assert result.candidate['gatherSpec']['contract']['outputContractDigest'] == context['frozenCollectionVersion']['outputContractDigest']
                assert diagnostics[-1]['validated'] and diagnostics[-1]['budget']['calls'] == (3 if PAGINATION else 2)
                if PAGINATION:
                    spec = result.candidate['gatherSpec']['collect']['list']
                    assert spec['pagination']['type'] == 'next_link'
                    assert discover_records_from_spec(listing, context['sourceUrl'], spec)[1].endswith('/index_2.html')
                status = 'validated'
            except BudgetError as exc:
                assert broken and exc.code == 'MODEL_NO_PROGRESS'
                assert diagnostics[-1]['budget']['calls'] == (6 if PAGINATION else 5) and not diagnostics[-1]['validated']
                status = exc.code
        results.append({'case': 'changing_bad_selector' if broken else 'valid_four_field_contract',
                        'status': status, 'phases': phases, 'diagnostic': diagnostics[-1]})
    assert store.get_collector(collector['id']) == collector
    report = {'mode': 'complete explorer loop with deterministic model and browser fixtures',
              'realModelCalls': 0, 'realNetworkRequests': 0, 'databaseWrites': 0, 'published': False, 'results': results}
    (OUT / ('pagination-replay.json' if PAGINATION else 'validation-loop-replay.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
