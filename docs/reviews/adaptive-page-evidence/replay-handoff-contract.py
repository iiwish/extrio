"""Offline replay with the current Worker contract and saved public snapshots; no model calls."""
import asyncio
import json
from pathlib import Path

from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer
from extrio.harvest import discover_records_from_spec
from extrio.model_gateway import ActiveModel, ModelRuleCompiler
from extrio.store import Store

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


async def main():
    settings = get_settings()
    store = Store(settings.database_path)
    collector = store.get_collector('collector_ggzyfw_beijing_gov_cn_53130add')
    context = store.collector_compilation_context(collector)
    snapshots = settings.artifact_path / 'op_x_9f15867e315c4b'
    discovery = json.loads((snapshots / 'discovery-plan.json').read_text())
    listing = (snapshots / 'list-001.html').read_text()
    records, _ = discover_records_from_spec(listing, context['sourceUrl'], discovery['list'])
    urls = list(dict.fromkeys(row['detailUrl'] for row in records))[:3]
    samples = [(url, (snapshots / f'detail-{i:03d}.html').read_text()) for i, url in enumerate(urls, 1)]
    fixture = {'detail': {'fields': {
        'title': {'selector': 'css:meta[http-equiv="ArticleTitle"]::attr(content)'},
        'content': {'selector': 'css:div.div-content::html', 'valueType': 'html', 'required': False},
        'publish_date': {'selector': 'css:meta[http-equiv="PubDate"]::attr(content)', 'required': False,
                         'transforms': [{'type': 'regex_extract', 'pattern': '[0-9]{4}-[0-9]{2}-[0-9]{2}', 'group': 0}]},
    }}, 'bindings': {'detailUrl': 'list.detailUrl', 'title': 'detail.title', 'content': 'detail.content'}}
    compiler = ModelRuleCompiler(store, CredentialCipher(settings.credential_encryption_key_path))
    compiler._model = lambda: ActiveModel('custom', 'https://offline.invalid', 'deterministic-fixture', '')

    async def complete(_model, _system, evidence, **_kwargs):
        assert evidence['expectedFields'] == context['expectedFields']
        return fixture

    compiler._complete_json = complete
    compiled = await compiler.compile(context, context['sourceUrl'], listing, samples, discovery)
    explorer = Crawl4AIExplorer(ContractBundle(ROOT / 'docs/contracts'), Path('/tmp/extrio-offline-handoff'), compiler)
    result = explorer._validate_candidate(context, context, 'offline', context['sourceUrl'], listing, samples, compiled, None, {})
    assert len(result.preview_items) == 3
    assert all(item['decision'] == 'accepted' for item in result.preview_items)
    assert [item['extractedData']['detail_url'] for item in result.preview_items] == urls
    assert all(set(item['extractedData']) == {field['key'] for field in context['expectedFields']} for item in result.preview_items)
    assert result.candidate['gatherSpec']['contract']['outputContractDigest'] == context['frozenCollectionVersion']['outputContractDigest']
    assert store.get_collector(collector['id']) == collector
    report = {'mode': 'deterministic offline fixture, not real model acceptance', 'realModelCalls': 0,
              'databaseWrites': 0, 'published': False, 'samplesAccepted': 3,
              'contextSource': 'Store.collector_compilation_context (Worker equivalent)',
              'outputFields': [field['key'] for field in context['expectedFields']],
              'handoff': compiled.plan['bindings']['detailUrl'], 'frozenContractPreserved': True,
              'businessUrlsMatchDetailSamples': True}
    (OUT / 'handoff-contract-replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
