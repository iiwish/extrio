"""One authorized live model verification, with no application database writes or publication."""
import asyncio
import json
from pathlib import Path

from extrio.adaptive_compile import CURRENT_SESSION
from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer
from extrio.model_gateway import ModelRuleCompiler
from extrio.store import Store

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REPORT = OUT / 'round-efficiency-live.json'
COLLECTOR = 'collector_ggzyfw_beijing_gov_cn_53130add'


async def main():
    if REPORT.exists():
        raise SystemExit('Verification already attempted; do not spend another authorization.')
    settings = get_settings()
    store = Store(settings.database_path)
    collector = store.get_collector(COLLECTOR)
    compilation_context = store.collector_compilation_context(collector)
    compiler = ModelRuleCompiler(store, CredentialCipher(settings.credential_encryption_key_path))
    model = compiler._model()
    calls = []
    diagnostics = []
    original = compiler._complete_json

    async def tracked(*args, **kwargs):
        row = {'purpose': kwargs.get('purpose'), 'call': CURRENT_SESSION.get().budget.calls}
        calls.append(row)
        try:
            raw = await original(*args, **kwargs)
            row['action'] = raw.get('action', 'direct_rule')
            if raw.get('action') in {'read_nodes', 'expand_nodes'}:
                row['requests'] = raw.get('requests')
            row['status'] = 'returned'
            return raw
        except Exception as exc:
            row['status'] = 'failed'
            row['code'] = getattr(exc, 'code', type(exc).__name__)
            raise

    compiler._complete_json = tracked

    async def report(summary):
        diagnostics.append(summary)

    async def progress(stage, percent, metrics):
        print(json.dumps({'stage': stage, 'percent': percent, 'metrics': metrics}), flush=True)

    result = {'status': 'started', 'model': model.model, 'provider': model.provider,
              'sourceUrl': collector['sourceUrl'], 'maxCalls': 16, 'published': False,
              'databaseWrites': 0, 'calls': calls}
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    explorer = Crawl4AIExplorer(ContractBundle(ROOT / 'docs/contracts'),
                               Path('/tmp/extrio-round-efficiency-verification'), compiler,
                               allow_http=lambda: store.get_platform_setting('allowAnonymousHttp') is not False)
    try:
        candidate = await explorer.explore(compilation_context, 'standalone-verification', progress, diagnostic=report)
        result.update(status='validated', previewCount=len(candidate.preview_items),
                      accepted=sum(item['decision'] == 'accepted' for item in candidate.preview_items))
        path = Path('/tmp/extrio-round-efficiency-verification/candidate.json')
        path.write_text(json.dumps(candidate.candidate, ensure_ascii=False, indent=2))
        result['candidatePath'] = str(path)
    except Exception as exc:
        result.update(status='failed', code=getattr(exc, 'code', type(exc).__name__))
    finally:
        result['diagnostic'] = diagnostics[-1] if diagnostics else None
        result['collectorUnchanged'] = store.get_collector(COLLECTOR) == collector
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
