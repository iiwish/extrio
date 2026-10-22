import json
import re
from pathlib import Path

import httpx

ROOT = Path('/tmp/extrio-p2-qa')
INSTANCE = Path('/tmp/g4-qa-p2-reliability-20261022')
API = 'http://127.0.0.1:8056'


def main():
    state = json.loads((INSTANCE / 'state.json').read_text())
    assert state['apiUrl'] == API
    events = [json.loads(line) for line in (ROOT / 'proxy-events.jsonl').read_text().splitlines() if line]
    first, second, third = events[:3]
    for event in (first, second, third):
        assert event['method'] == 'POST' and event['path'] == '/api/v1/collectors/batch' and event['status'] == 200
        assert re.fullmatch(r'[a-f0-9]{64}', event['keyHash'])
        assert re.fullmatch(r'[a-f0-9]{64}', event['bodyHash'])
    assert first['droppedAfterCommit'] is True and first['replayed'] is False
    assert second['replayed'] is True and second['droppedAfterCommit'] is False
    assert first['keyHash'] == second['keyHash'] and first['bodyHash'] == second['bodyHash']
    assert first['collectionId'] and first['collectionId'] == second['collectionId']
    assert len(first['collectorIds']) == 1 and first['collectorIds'] == second['collectorIds']
    assert first['createdCount'] == second['createdCount'] == 1
    assert first['rejectedCount'] == second['rejectedCount'] == 0
    assert third['collectionId'] is None and third['collectorIds'] == []
    assert third['createdCount'] == 0 and third['rejectedCount'] == 1
    assert third['keyHash'] != first['keyHash']

    credentials = json.loads((INSTANCE / 'qa-login.json').read_text())
    with httpx.Client(base_url=API + '/api/v1', timeout=20, trust_env=False) as client:
        client.post('/auth/login', json=credentials).raise_for_status()
        detail_response = client.get('/collections/' + first['collectionId'])
        detail_response.raise_for_status()
        requirement = detail_response.json()
        assert requirement['id'] == first['collectionId']
        assert len(requirement['sources']) == 1
        assert requirement['sources'][0]['id'] == first['collectorIds'][0]
        source = requirement['sources'][0]
        assert source['collectionId'] == requirement['id']
        assert source['sourceUrl'].startswith(state['sourceUrl'])
        source_response = client.get('/collectors/' + source['id'])
        source_response.raise_for_status()
        assert source_response.json()['collectionId'] == requirement['id']

        all_collectors = []
        page = 1
        while True:
            response = client.get('/collectors', params={'lifecycle': 'all', 'page': page, 'limit': 200})
            response.raise_for_status()
            batch = response.json()
            all_collectors.extend(batch['items'])
            if len(all_collectors) >= batch['total']:
                break
            page += 1
            assert page <= 100
        assert sum(value['sourceUrl'] == source['sourceUrl'] for value in all_collectors) == 1
        response = client.get('/collections')
        response.raise_for_status()
        all_requirements = response.json()['items']
        assert sum(value['id'] == requirement['id'] for value in all_requirements) == 1
        assert not any(value['name'] == 'P2 all-rejected QA' for value in all_requirements)

    result = {
        'result': 'PASS',
        'apiUrl': API,
        'proxyEventCountObserved': len(events),
        'firstResponseDroppedAfterCommit': first['droppedAfterCommit'],
        'retryReplayed': second['replayed'],
        'sameNonemptyKeyHash': first['keyHash'] == second['keyHash'],
        'sameBodyHash': first['bodyHash'] == second['bodyHash'],
        'sameCollectionId': first['collectionId'] == second['collectionId'],
        'sameCollectorIds': first['collectorIds'] == second['collectorIds'],
        'collectionId': requirement['id'],
        'collectorId': source['id'],
        'sourceCountInRequirement': len(requirement['sources']),
        'matchingSourceUrlCountInInstance': sum(value['sourceUrl'] == source['sourceUrl'] for value in all_collectors),
        'allRejectedCollectionId': third['collectionId'],
        'allRejectedEmptyRequirementPresent': False,
        'instanceRequirementCountObserved': len(all_requirements),
        'instanceCollectorCountObserved': len(all_collectors),
        'limitations': 'Read-only API object/count verification and captured proxy receipts; no inference that the whole instance contains only one object.',
    }
    output = ROOT / 'creation-runtime-check.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
