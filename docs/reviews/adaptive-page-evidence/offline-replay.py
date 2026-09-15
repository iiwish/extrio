"""Replay saved public snapshots with a deterministic model fixture, never a paid API."""
import asyncio
import json
from pathlib import Path

from extrio.adaptive_compile import CURRENT_SESSION
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer
from extrio.harvest import discover_records_from_spec
from extrio.model_budget import BudgetError
from extrio.model_gateway import ActiveModel, ModelRuleCompiler
from extrio.store import Store

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SNAPSHOTS = ROOT / 'backend/data/artifacts/op_x_93ab79c70dd54e'
BACKUP = Path('/tmp/extrio-before-adaptive-acceptance-20260911.db')
COLLECTOR = 'collector_ggzyfw_beijing_gov_cn_f4d99adb'


async def main():
    assert BACKUP.exists() and SNAPSHOTS.is_dir()
    store = Store(BACKUP)
    collector = store.get_collector(COLLECTOR)
    old = collector['candidate']['gatherSpec']
    listing = (SNAPSHOTS / 'list-001.html').read_text()
    records, _ = discover_records_from_spec(listing, collector['sourceUrl'], old['collect']['list'])
    urls = list(dict.fromkeys(row['detailUrl'] for row in records))[:3]
    samples = [(url, (SNAPSHOTS / f'detail-{i:03d}.html').read_text()) for i, url in enumerate(urls, 1)]
    results = []
    for window in (8192, 16384, 32768, 131072):
        compiler = ModelRuleCompiler(store, CredentialCipher(Path('/tmp/extrio-offline-unused-key')))
        compiler._model = lambda: ActiveModel('custom', 'https://offline.invalid', 'deterministic-fixture', '', {
            'contextTokens': window, 'maxInputTokens': window, 'maxOutputTokens': 1024, 'reasoningTokens': 0})
        calls = []

        async def model_fixture(_model, _system, evidence, **_kwargs):
            session = CURRENT_SESSION.get()
            calls.append({'inputReservation': session.current_reservation.input_tokens,
                          'evidencePages': sorted({row['pageId'] for row in evidence['evidence']})})
            session.budget.settle(session.current_reservation, None, 200)
            if len(calls) == 1:
                requests = []
                for hint in evidence['directoryHints']:
                    if hint['pageId'].startswith('detail-'):
                        node = next((node for node in hint['nodes'] if node['tag'] == 'table'), None)
                        assert node is not None, 'deep content must be directly addressable without wrapper expansion'
                        requests.append({'pageId': hint['pageId'], 'nodeId': node['nodeId']})
                assert len(requests) == 3
                return {'action': 'read_nodes', 'requests': requests}
            assert calls[-1]['evidencePages'] == ['detail-1', 'detail-2', 'detail-3']
            return {'action': 'propose_rule', 'rule': {'list': old['collect']['list'], 'detail': old['collect']['detail']}}

        compiler._complete_json = model_fixture
        explorer = Crawl4AIExplorer(ContractBundle(ROOT / 'docs/contracts'), Path('/tmp/extrio-offline-unused-artifacts'), compiler)
        with compiler.task_session() as session:
            try:
                compiled = await compiler.compile_repair_rule_plan(collector, collector['sourceUrl'], listing, samples, old)
                result = explorer._validate_candidate(collector, collector, 'offline', collector['sourceUrl'], listing, samples, compiled, old, {})
                assert result.candidate['gatherSpec']['contract'] == old['contract']
                assert all(item['decision'] == 'accepted' for item in result.preview_items)
                assert len({item['entityKey'] for item in result.preview_items}) == 3
                assert all(item['extractedData']['detailUrl'] == item['sourceUrl'] for item in result.preview_items)
                results.append({'window': window, 'status': 'fixture_validated', 'calls': calls,
                                'readPages': [page['pageId'] for page in session.summary()['pages'] if page['readNodes']],
                                'accepted': len(result.preview_items)})
            except BudgetError as exc:
                assert not calls and exc.code == 'MODEL_CONTEXT_INSUFFICIENT'
                results.append({'window': window, 'status': exc.code, 'calls': calls})
    assert all(row['status'] == 'fixture_validated' for row in results if row['window'] >= 32768)
    report = {'model': 'deterministic fixture, not the real provider', 'realModelCalls': 0, 'databaseWrites': 0, 'results': results}
    (OUT / 'offline-replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
