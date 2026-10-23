import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path('/tmp/extrio-p2-qa')
INSTANCE = Path('/tmp/g4-qa-p2-reliability-20261022')
API = 'http://127.0.0.1:8056'
RUN = 'run_de236f0d54f14a58'
VERSION = 'colver_collection_x_93475b760872420c81652bf54199f28f_v1'
TITLE = 'G4 public fixture notice'
SOURCE = 'http://127.0.0.1:59007/notice?case=full-journey'


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main():
    state = json.loads((INSTANCE / 'state.json').read_text())
    assert state['apiUrl'] == API and state['sourceUrl'] + '?case=full-journey' == SOURCE
    model_before = records(INSTANCE / 'synthetic-model.jsonl')
    assert len(model_before) == 2
    assert [record['phase'] for record in model_before] == ['discover', 'compile']
    assert all(record['synthetic'] is True for record in model_before)
    credentials = json.loads((INSTANCE / 'qa-login.json').read_text())
    with httpx.Client(base_url=API + '/api/v1', timeout=20, trust_env=False) as client:
        client.post('/auth/login', json=credentials).raise_for_status()
        del credentials
        response = client.get('/runs/' + RUN)
        response.raise_for_status()
        run = response.json()
        assert run['id'] == RUN and run['status'] == 'succeeded'
        assert run['acceptedCount'] == 1 and run['rejectedCount'] == 0 and len(run['items']) == 1
        item = run['items'][0]
        assert item['extractedData'] == {'title': TITLE}
        assert item['lineage']['collectionVersion'] == VERSION
        assert run['integrityStatus'] == 'verified' and run['policyContextStatus'] == 'fixed'
        assert run['ruleAttestationId'] and run['signingKeyId'] and run['ruleDigest'].startswith('sha256:')
        started = datetime.fromisoformat(run['startedAtIso'].replace('Z', '+00:00')).astimezone(UTC)
        assert all(datetime.fromisoformat(record['at']).astimezone(UTC) < started for record in model_before)

        response = client.get('/collectors/' + run['collectorId'])
        response.raise_for_status()
        collector = response.json()
        assert collector['sourceUrl'] == SOURCE and collector['activeRuleVersion'] == run['ruleVersion']
        source_context = collector['candidate']['gatherSpec']['sourceContext']
        assert SOURCE in source_context['entrypoints']

        response = client.get('/items/export', params={'format': 'csv', 'runId': RUN})
        response.raise_for_status()
        csv_rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        assert len(csv_rows) == 1 and csv_rows[0]['title'] == TITLE
        assert csv_rows[0]['entityKey'] == item['entityKey'] and csv_rows[0]['decision'] == 'accepted'
        response = client.get('/items/export', params={'format': 'jsonl', 'runId': RUN})
        response.raise_for_status()
        jsonl_rows = [json.loads(line) for line in response.text.splitlines() if line]
        assert len(jsonl_rows) == 1 and jsonl_rows[0]['title'] == TITLE
        assert jsonl_rows[0]['entityKey'] == item['entityKey'] and jsonl_rows[0]['decision'] == 'accepted'

    receiver = records(INSTANCE / 'receiver.jsonl')
    assert len(receiver) == 1 and receiver[0]['valid'] is True
    model_after = records(INSTANCE / 'synthetic-model.jsonl')
    assert model_after == model_before
    summary = {
        'result': 'PASS',
        'apiUrl': API,
        'runId': RUN,
        'status': run['status'],
        'acceptedCount': run['acceptedCount'],
        'rejectedCount': run['rejectedCount'],
        'title': item['extractedData']['title'],
        'entityKey': item['entityKey'],
        'collectionVersion': item['lineage']['collectionVersion'],
        'integrityStatus': run['integrityStatus'],
        'policyContextStatus': run['policyContextStatus'],
        'ruleVersion': run['ruleVersion'],
        'ruleAttestationId': run['ruleAttestationId'],
        'signingKeyId': run['signingKeyId'],
        'trustRevision': run['trustRevision'],
        'sourceUrl': collector['sourceUrl'],
        'sourcePinnedToOwnedFixture': True,
        'receiverRecords': len(receiver),
        'receiverAllValid': True,
        'syntheticModelRecordsBefore': len(model_before),
        'syntheticModelRecordsAfter': len(model_after),
        'syntheticModelPhases': [record['phase'] for record in model_after],
        'modelCallsPrecedeRunStart': True,
        'csvRows': len(csv_rows),
        'jsonlRows': len(jsonl_rows),
        'exportsMatchTitleEntityAndDecision': True,
        'limitations': 'Read-only API integrity/lineage/source and fixture HMAC receiver checks; no independent Ed25519 verification. Synthetic model protocol fixture is not real-model quality evidence.',
    }
    (ROOT / 'journey-runtime-check.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
