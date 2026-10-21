import copy

import pytest
from test_api import ready_review_collector
from test_collection_versions import client as client
from test_worker import accepted_item

import extrio.app as app_module
from extrio.runtime import RunResult
from extrio.store import DEFAULT_COLLECTION_POLICY
from extrio.worker import Worker


@pytest.mark.parametrize('cancel_finalization', [False, True])
async def test_capped_progress_is_atomic_and_reused_with_its_fixed_window(client, cancel_finalization):
    store = app_module.store
    source = ready_review_collector(store)
    store.create_collection_policy(source['id'], {**DEFAULT_COLLECTION_POLICY, 'maxPages': 3, 'maxItems': 50,
                                                 'checkpointMode': 'observed'})
    decisions = {field['key']: 'risk_accepted' if field['key'] == 'budget' else 'approved' for field in source['candidate']['fields']}
    assert client.post(f"/api/v1/collectors/{source['id']}/publish", json={'reviewDecisions': decisions},
                       headers={'Idempotency-Key': 'coverage-capped-publish'}).status_code == 200
    contexts = []

    class Runtime:
        async def run(self, collector, run, progress):
            contexts.append(copy.deepcopy(run))
            continuation = {'ruleDigest': run['ruleDigest'], 'policyVersionId': collector['collectionPolicy']['id'],
                'windowStart': run['windowStart'], 'resumeUrl': 'https://example.com/list?page=3', 'pageIndex': 2,
                'anchorUrl': 'https://example.com/a', 'processedUrls': [], 'olderPagesBefore': 0, 'watermark': '2026-10-19'}
            complete = len(contexts) == 2
            if cancel_finalization:
                response = client.post(f"/api/v1/operations/{run['operationId']}/cancel",
                                       headers={'Idempotency-Key': 'coverage-cancel-finalize'})
                assert response.status_code == 200
            return RunResult([], {'listPagesFetched': 3, 'detailPagesFetched': 0, 'detailUrlsDiscovered': 0,
                'recordsOutsideWindow': 0, 'duplicateDetailUrls': 0, 'newItems': 0, 'updatedItems': 0,
                'unchangedItems': 0, 'warningCount': 0}, 'time_window_reached' if complete else 'max_pages', '.1s',
                '2026-10-19', coverage_progress=None if complete else continuation, coverage_complete=complete)

    worker = Worker.__new__(Worker)
    worker.store, worker.contracts, worker.runtime = store, app_module.contracts, Runtime()
    first = client.post(f"/api/v1/collectors/{source['id']}/runs", headers={'Idempotency-Key': 'coverage-capped-first'})
    assert first.status_code == 202
    if cancel_finalization:
        with pytest.raises(RuntimeError, match='cancel'):
            await worker.process(store.claim_job(60))
        assert not store.get_collector(source['id']).get('coverageProgress')
        assert not store.get_checkpoint(source['id'])
        return
    await worker.process(store.claim_job(60))
    capped = store.get_run(first.json()['resourceId'])
    assert capped['checkpointAfter'] is None and capped['coverageProgressAfter']['pageIndex'] == 2
    assert store.get_collector(source['id'])['coverageProgress'] == capped['coverageProgressAfter']
    second = client.post(f"/api/v1/collectors/{source['id']}/runs", headers={'Idempotency-Key': 'coverage-capped-second'})
    assert second.status_code == 202
    await worker.process(store.claim_job(60))
    assert contexts[1]['windowStart'] == contexts[0]['windowStart']
    assert contexts[1]['coverageProgressBefore'] == capped['coverageProgressAfter']
    completed = store.get_run(second.json()['resourceId'])
    assert completed['checkpointAfter']['kind'] == 'coverage' and completed['coverageProgressAfter'] is None
    assert store.get_collector(source['id'])['coverageProgress'] is None


async def test_quality_backlog_is_durable_before_coverage_and_explicit_retry_does_not_move_it(client):
    store = app_module.store
    source = ready_review_collector(store)
    store.create_collection_policy(source['id'], {**DEFAULT_COLLECTION_POLICY, 'maxPages': 3, 'maxItems': 50,
                                                 'checkpointMode': 'observed'})
    decisions = {field['key']: 'risk_accepted' if field['key'] == 'budget' else 'approved' for field in source['candidate']['fields']}
    published = client.post(f"/api/v1/collectors/{source['id']}/publish", json={'reviewDecisions': decisions},
                            headers={'Idempotency-Key': 'observed-publish'})
    assert published.status_code == 200, published.text

    class Runtime:
        async def run(self, collector, run, progress):
            item = accepted_item(run_id=run['id'])
            item.update(collectorId=source['id'], collectorName=source['name'])
            item['lineage']['listRecord'] = {'listTitle': 'Notice A', 'detailUrl': item['sourceUrl']}
            if run.get('runPurpose') != 'retry_rejected':
                item.update(decision='rejected', revision=None, changeType=None, content='', observationHistory=[])
                item['lineage']['observationId'] = None
            else:
                assert run['retryRecords'] == [item['lineage']['listRecord']]
            return RunResult([item], {'listPagesFetched': 1, 'detailPagesFetched': 1, 'detailUrlsDiscovered': 1,
                'recordsOutsideWindow': 0, 'duplicateDetailUrls': 0, 'newItems': 0, 'updatedItems': 0,
                'unchangedItems': 0, 'warningCount': 0}, 'next_link_exhausted', '.1s', '2026-10-19', coverage_complete=True)

    worker = Worker.__new__(Worker)
    worker.store, worker.contracts, worker.runtime = store, app_module.contracts, Runtime()
    first = client.post(f"/api/v1/collectors/{source['id']}/runs", headers={'Idempotency-Key': 'observed-initial-run-01'})
    assert first.status_code == 202, first.text
    job = store.claim_job(60)
    await worker.process(job)
    run = store.get_run(first.json()['resourceId'])
    assert run['status'] == 'partially_succeeded' and run['pendingQualityCount'] == 1
    assert run['checkpointAfter']['kind'] == 'coverage'
    assert run['items'][0]['decision'] == 'rejected' and run['items'][0]['revision'] is None
    checkpoint = copy.deepcopy(store.get_checkpoint(source['id']))
    retry = client.post(f"/api/v1/collectors/{source['id']}/reprocess-rejected", headers={'Idempotency-Key': 'observed-retry-run-01'})
    assert retry.status_code == 202, retry.text
    assert client.post(f"/api/v1/collectors/{source['id']}/reprocess-rejected",
                       headers={'Idempotency-Key': 'observed-retry-run-01'}).json() == retry.json()
    job = store.claim_job(60)
    await worker.process(job)
    retried = store.get_run(retry.json()['resourceId'])
    assert retried['pendingQualityCount'] == 0 and retried['items'][0]['revision'] == 1
    assert retried['checkpointAfter'] is None and store.get_checkpoint(source['id']) == checkpoint
    assert store.get_run(first.json()['resourceId'])['items'][0]['decision'] == 'rejected'
    assert client.post(f"/api/v1/collectors/{source['id']}/reprocess-rejected",
                       headers={'Idempotency-Key': 'observed-retry-empty'}).status_code == 409

    old_run = copy.deepcopy(store.get_run(first.json()['resourceId']))
    old_item = copy.deepcopy(store.get_item(old_run['items'][0]['id']))
    old_policy = copy.deepcopy(store.get_collector(source['id'])['collectionPolicy'])
    body = {key: old_policy[key] for key in (*DEFAULT_COLLECTION_POLICY, 'checkpointMode')}
    replaced = client.post(f"/api/v1/collectors/{source['id']}/collection-policy", json=body,
                          headers={'Idempotency-Key': 'observed-recovery-policy'})
    assert replaced.status_code == 200
    assert replaced.json()['collectionPolicy']['id'] != old_policy['id']
    assert replaced.json()['checkpoint'] is None and not replaced.json().get('coverageProgress')
    assert store.get_collection_policy(old_policy['id']) == old_policy
    assert store.get_run(old_run['id']) == old_run and store.get_item(old_item['id']) == old_item
    restarted = client.post(f"/api/v1/collectors/{source['id']}/runs",
                            headers={'Idempotency-Key': 'observed-recovery-initial'})
    assert restarted.status_code == 202
    restarted_run = store.get_run(restarted.json()['resourceId'])
    assert restarted_run['executionMode'] == 'initial' and restarted_run['checkpointBefore'] is None


async def test_rate_limited_result_keeps_durable_progress_without_items_or_checkpoint(client):
    store = app_module.store
    source = ready_review_collector(store)
    store.create_collection_policy(source['id'], {**DEFAULT_COLLECTION_POLICY, 'maxPages': 3, 'maxItems': 50,
                                                 'checkpointMode': 'observed'})
    decisions = {f['key']: 'risk_accepted' if f['key'] == 'budget' else 'approved' for f in source['candidate']['fields']}
    assert client.post(f"/api/v1/collectors/{source['id']}/publish", json={'reviewDecisions': decisions},
                       headers={'Idempotency-Key': 'rate-limit-publish'}).status_code == 200
    contexts = []

    class Runtime:
        async def run(self, collector, run, progress):
            contexts.append(copy.deepcopy(run))
            prior = run.get('coverageProgressBefore') or {
                'ruleDigest': run['ruleDigest'], 'policyVersionId': collector['collectionPolicy']['id'],
                'windowStart': run['windowStart'], 'resumeUrl': 'https://example.com/list?page=3',
                'pageIndex': 2, 'anchorUrl': 'https://example.com/a', 'processedUrls': [],
                'olderPagesBefore': 0, 'watermark': '2026-10-19'}
            return RunResult([], {'listPagesFetched': 2, 'detailPagesFetched': 0, 'detailUrlsDiscovered': 0,
                'recordsOutsideWindow': 0, 'duplicateDetailUrls': 0, 'newItems': 0, 'updatedItems': 0,
                'unchangedItems': 0, 'warningCount': 1}, 'max_pages' if len(contexts) == 1 else 'source_rate_limited',
                '.1s', coverage_progress=prior, coverage_complete=False)

    worker = Worker.__new__(Worker)
    worker.store, worker.contracts, worker.runtime = store, app_module.contracts, Runtime()
    for number in range(2):
        op = client.post(f"/api/v1/collectors/{source['id']}/runs",
                         headers={'Idempotency-Key': f'rate-limit-run-{number}'}).json()
        await worker.process(store.claim_job(60))
        if number == 0:
            prior = copy.deepcopy(store.get_collector(source['id'])['coverageProgress'])
    run = store.get_run(op['resourceId'])
    assert run['status'] == 'failed' and run['paginationStopReason'] == 'source_rate_limited'
    assert not run['checkpointAfter'] and not run['items'] and not store.get_checkpoint(source['id'])
    assert store.get_collector(source['id'])['coverageProgress'] == prior == run['coverageProgressAfter']
