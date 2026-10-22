import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from test_collection_versions import client as client

import extrio.app as app_module
from extrio import bounded_recovery as recovery
from extrio.harvest import build_candidate
from extrio.store import DEFAULT_COLLECTION_POLICY

NOW = datetime(2026, 10, 20, 1, tzinfo=UTC)
AUDIT = {'tenantId': 'local', 'actorId': 'test', 'requestId': 'recovery-test'}


def seed(client, *, host='example.com'):
    store = app_module.store
    source = store.create_collector('Source', 'Collect', f'https://{host}/list', host)
    source.update(status='ready_review', candidate=build_candidate(
        source, app_module.contracts,
        '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a></li></ul>',
        [(f'https://{host}/detail/1', '<h1 class="notice-title">A</h1><div class="meta">'
          '<span data-field="buyer">B</span><time datetime="2026-08-31T00:00:00Z"></time></div>')],
    ))
    store.save_collector(source)
    store.create_collection_policy(source['id'], {**DEFAULT_COLLECTION_POLICY, 'maxPages': 3, 'maxItems': 50,
                                                 'checkpointMode': 'observed'})
    decisions = {f['key']: 'risk_accepted' if f['key'] == 'budget' else 'approved' for f in source['candidate']['fields']}
    assert client.post(f"/api/v1/collectors/{source['id']}/publish", json={'reviewDecisions': decisions},
                       headers={'Idempotency-Key': 'recovery-publish'}).status_code == 200
    operation = app_module.create_run_operation(source['id'])
    run = store.get_run(operation['resourceId'])
    progress = {'ruleDigest': run['ruleDigest'], 'policyVersionId': run['policyVersion'],
        'windowStart': '2026-09-19', 'resumeUrl': f'https://{host}/list?page=99', 'pageIndex': 98,
        'anchorUrl': f'https://{host}/a', 'processedUrls': [f'https://{host}/a'], 'olderPagesBefore': 0}
    run.update(status='failed', paginationStopReason='source_rate_limited', windowStart='2026-09-19',
               coverageProgressBefore=progress, coverageProgressAfter=progress, finishedAtIso=NOW.isoformat())
    with store.transaction() as connection:
        store.save_run(run, connection)
        store.update_operation(operation['id'], connection=connection, status='succeeded')
        connection.execute("UPDATE jobs SET status='completed' WHERE operation_id=?", (operation['id'],))
        current = store.get_collector(source['id'], connection)
        current.update(coverageProgress=progress, activeOperationId=None, latestRunId=run['id'])
        store.save_collector(current, connection)
    return store, source['id'], run


def start(store, run, key='recovery-001', now=NOW):
    return recovery.start(store, run['id'], key, AUDIT, now=now)[1]


def finish(store, batch, *, stop='source_rate_limited', retry_after=None, now=NOW + timedelta(minutes=31)):
    run = store.get_run(batch['activeRunId'])
    progress = copy.deepcopy(run['coverageProgressBefore'])
    if stop == 'max_pages':
        progress.update(pageIndex=100, resumeUrl='https://example.com/list?page=101')
    run.update(status='failed' if stop == 'source_rate_limited' else 'succeeded', paginationStopReason=stop,
               coverageProgressAfter=progress, finishedAtIso=now.isoformat(), retryAfterSeconds=retry_after)
    with store.transaction() as connection:
        store.save_run(run, connection)
        store.update_operation(run['operationId'], connection=connection, status='succeeded')
        connection.execute("UPDATE jobs SET status='completed' WHERE operation_id=?", (run['operationId'],))
        source = store.get_collector(run['collectorId'], connection)
        source.update(activeOperationId=None, latestRunId=run['id'], coverageProgress=progress)
        store.save_collector(source, connection)
    return run


def test_persistent_cooldown_idempotency_and_one_resumed_run(client):
    store, cid, old = seed(client)
    before = copy.deepcopy(store.get_run(old['id']))
    batch = start(store, old)
    assert batch['status'] == 'cooling_down' and batch['attemptRunIds'] == []
    assert start(store, old) == batch
    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=29)) == 0
    assert store.get_collector(cid)['schedule']['enabled'] is False
    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=30)) == 1
    active = recovery.for_run(store, old['id'])
    assert len(active['attemptRunIds']) == 1 and active['reservedRequests'] == 120
    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=30)) == 0
    run = store.get_run(active['activeRunId'])
    assert run['coverageProgressBefore'] == old['coverageProgressAfter'] and run['windowStart'] == '2026-09-19'
    assert run['sourceRequestLimit'] == 120 and run['recoveryBatchId'] == batch['id']
    finish(store, active, stop='max_pages')
    recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=32))
    completed = recovery.for_run(store, old['id'])
    assert completed['status'] == 'recovered' and completed['reason'] == 'continuation_verified'
    assert store.get_checkpoint(cid) is None
    assert store.get_run(old['id']) == before


@pytest.mark.parametrize('key_status', ['retired', 'compromised'])
def test_untrusted_signing_key_stops_recovery_without_reserving_a_run(client, key_status):
    store, cid, old = seed(client)
    before = copy.deepcopy(store.get_run(old['id']))
    batch = start(store, old)
    store.update_signing_key_status(old['signingKeyId'], key_status, actor_id='test', request_id='recovery-key-status')

    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=31)) == 0
    stopped = recovery.get(store, batch['id'])
    assert stopped['status'] == 'needs_attention' and stopped['reason'] == 'dispatch_rejected'
    assert stopped['nextAttemptAt'] is None and stopped['finishedAt'] is not None
    assert stopped['activeRunId'] is None and stopped['attemptRunIds'] == [] and stopped['reservedRequests'] == 0
    assert not store.has_active_run(cid)
    assert store.get_collector(cid)['coverageProgress'] == old['coverageProgressAfter']
    assert store.get_collector(cid)['schedule']['enabled'] is False
    assert store.get_run(old['id']) == before
    assert store.get_signing_key(old['signingKeyId'])['status'] == key_status

    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=32)) == 0
    assert recovery.get(store, batch['id']) == stopped


@pytest.mark.parametrize('key_status', ['retired', 'compromised'])
def test_signing_rejection_does_not_block_another_valid_recovery(client, monkeypatch, tmp_path, key_status):
    store, cid, old = seed(client)
    rejected = start(store, old)
    monkeypatch.setattr(app_module, 'rule_signer', app_module.LocalEd25519Signer(tmp_path / 'valid.pem', 'signing_valid'))
    _, other_cid, other = seed(client, host='other.example')
    valid = start(store, other, key='recovery-valid-002', now=NOW + timedelta(seconds=1))
    before = {run['id']: copy.deepcopy(store.get_run(run['id'])) for run in (old, other)}
    store.update_signing_key_status(old['signingKeyId'], key_status, actor_id='test', request_id='recovery-key-status')

    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=31)) == 1
    assert recovery.get(store, rejected['id'])['status'] == 'needs_attention'
    assert not store.has_active_run(cid)
    running = recovery.get(store, valid['id'])
    assert running['status'] == 'running' and len(running['attemptRunIds']) == 1 and running['reservedRequests'] == 120
    resumed = store.get_run(running['activeRunId'])
    assert resumed['collectorId'] == other_cid and resumed['integrityStatus'] == 'verified'
    assert resumed['signingKeyId'] == 'signing_valid' and resumed['sourceRequestLimit'] == 120
    assert resumed['coverageProgressBefore'] == other['coverageProgressAfter']
    assert resumed['recoveryBatchId'] == valid['id']
    assert all(store.get_run(identifier) == snapshot for identifier, snapshot in before.items())

    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=32)) == 0
    assert recovery.get(store, valid['id']) == running


def test_unknown_dispatch_error_remains_visible_and_rolls_back(client):
    store, _, old = seed(client)
    batch = start(store, old)

    def broken_dispatch(*args, **kwargs):
        raise KeyError('unexpected_dispatch_failure')

    with pytest.raises(KeyError, match='unexpected_dispatch_failure'):
        recovery.tick(store, broken_dispatch, now=NOW + timedelta(minutes=31))
    assert recovery.get(store, batch['id']) == batch


def test_rate_limit_backoff_exhaustion_is_not_reset_by_restart_or_new_command(client):
    store, _, old = seed(client)
    batch = start(store, old)
    moment = NOW + timedelta(minutes=30)
    for index, delay in enumerate((7200, 21600, None)):
        assert recovery.tick(store, app_module.create_run_operation, now=moment) == 1
        active = recovery.for_run(store, old['id'])
        finish(store, active, now=moment)
        recovery.tick(store, app_module.create_run_operation, now=moment)
        batch = recovery.for_run(store, old['id'])
        assert len(batch['attemptRunIds']) == index + 1
        if delay:
            assert batch['nextAttemptAt'] == (moment + timedelta(seconds=delay)).isoformat().replace('+00:00', 'Z')
            assert recovery.tick(store, app_module.create_run_operation, now=moment + timedelta(seconds=delay - 1)) == 0
            moment += timedelta(seconds=delay)
    assert batch['status'] == 'needs_attention' and batch['reason'] == 'attempt_limit'
    assert batch['reservedRequests'] == 360
    assert recovery.tick(store, app_module.create_run_operation, now=moment + timedelta(hours=1)) == 0
    with pytest.raises(recovery.RecoveryError, match='RECOVERY_ALREADY_EXISTS'):
        start(store, old, key='another-key')


@pytest.mark.parametrize('kind', ['contract', 'progress', 'deadline', 'retry_after'])
def test_drift_deadline_and_server_wait_never_dispatch_early(client, kind):
    store, cid, old = seed(client)
    if kind == 'retry_after':
        old['retryAfterSeconds'] = 90000
        store.save_run(old)
    batch = start(store, old)
    if kind in {'contract', 'progress'}:
        source = store.get_collector(cid)
        if kind == 'contract':
            source['intent'] += ' changed'
        else:
            source['coverageProgress']['pageIndex'] = 77
        store.save_collector(source)
    recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(hours=25 if kind == 'deadline' else 1))
    batch = recovery.for_run(store, old['id'])
    assert batch['status'] == 'needs_attention' and not batch['attemptRunIds']


def test_domain_gate_cancellation_and_role_boundaries(client):
    store, cid, old = seed(client)
    batch = start(store, old)
    with pytest.raises(ValueError, match='SOURCE_RECOVERY_ACTIVE'):
        app_module.create_run_operation(cid)
    route = f"/api/v1/runs/{old['id']}/recovery"
    assert client.get(route).json()['id'] == batch['id']
    response = client.post(f"/api/v1/recovery-batches/{batch['id']}/cancel", json={},
                           headers={'Idempotency-Key': 'cancel-recovery-0001'})
    assert response.status_code == 200 and response.json()['status'] == 'cancelled', response.text
    assert recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(hours=2)) == 0
    assert store.get_collector(cid)['schedule']['enabled'] is False


def test_two_dispatchers_reserve_one_attempt_and_overlapping_hosts_are_blocked(client):
    store, cid, old = seed(client)
    start(store, old)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: recovery.tick(store, app_module.create_run_operation,
                            now=NOW + timedelta(minutes=30)), range(2)))
    assert sorted(results) == [0, 1]
    batch = recovery.for_run(store, old['id'])
    assert len(batch['attemptRunIds']) == 1 and batch['reservedRequests'] == 120
    other = {**store.get_collector(cid), 'id': 'another-collector', 'sourceUrl': 'https://example.com/another'}
    with store.transaction() as connection, pytest.raises(recovery.RecoveryError, match='SOURCE_RECOVERY_ACTIVE'):
        recovery.guard_source_work(store, connection, other)


def test_expired_worker_lease_cannot_replay_a_recovery_attempt(client):
    store, _, old = seed(client)
    start(store, old)
    recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=30))
    job = store.claim_job(60)
    assert job['attempts'] == 1 and job['payload']['maxJobAttempts'] == 1
    with store.transaction() as connection:
        connection.execute("UPDATE jobs SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (job['id'],))
    assert store.claim_job(60) is None
    assert store.get_run(job['payload']['runId'])['status'] == 'failed'
    recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=32))
    batch = recovery.for_run(store, old['id'])
    assert batch['status'] == 'needs_attention' and len(batch['attemptRunIds']) == 1


def test_long_server_wait_survives_batch_terminal_state_and_blocks_manual_bypass(client):
    store, cid, old = seed(client)
    moment = datetime.now(UTC)
    old.update(finishedAtIso=moment.isoformat(), retryAfterSeconds=90000)
    store.save_run(old)
    batch = start(store, old, now=moment)
    assert batch['status'] == 'needs_attention'
    with pytest.raises(recovery.RecoveryError, match='SOURCE_RECOVERY_ACTIVE'):
        app_module.create_run_operation(cid)


def test_api_start_is_idempotent_and_rejects_unbounded_input(client):
    _, _, old = seed(client)
    path = f"/api/v1/runs/{old['id']}/recovery"
    key = {'Idempotency-Key': 'bounded-api-start-001'}
    first = client.post(path, json={}, headers=key)
    assert first.status_code == 201, first.text
    assert client.post(path, json={}, headers=key).json() == first.json()
    assert client.post(path, json={'maxAttempts': 1000}, headers={'Idempotency-Key': 'bounded-api-start-002'}).status_code == 422
    assert client.post(path, json={}, headers={'Idempotency-Key': 'bounded-api-start-003'}).status_code == 409
    assert client.get(f"/api/v1/recovery-batches/{first.json()['id']}").status_code == 200


@pytest.mark.parametrize('stop', ['source_structure_mismatch', 'coverage_order_unverified', 'cross_host_blocked'])
def test_non_rate_failures_never_receive_another_attempt(client, stop):
    store, _, old = seed(client)
    start(store, old)
    recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(minutes=30))
    batch = recovery.for_run(store, old['id'])
    finish(store, batch, stop=stop)
    recovery.tick(store, app_module.create_run_operation, now=NOW + timedelta(hours=1))
    batch = recovery.for_run(store, old['id'])
    assert batch['status'] == 'needs_attention' and len(batch['attemptRunIds']) == 1


def test_read_only_user_cannot_start_or_cancel_recovery(client, monkeypatch):
    store, _, old = seed(client)
    batch = start(store, old)
    monkeypatch.setattr(app_module, 'settings', app_module.settings.model_copy(update={'auth_enabled': True}))
    assert client.post('/api/v1/auth/setup', json={'username': 'admin', 'password': 'Admin-test-12345!'}).status_code == 200
    created = client.post('/api/v1/users', json={'username': 'viewer', 'password': 'Viewer-test-12345!',
        'displayName': 'Viewer', 'role': 'viewer'}, headers={'Idempotency-Key': 'bounded-create-viewer-01'})
    assert created.status_code == 201, created.text
    client.post('/api/v1/auth/logout')
    assert client.post('/api/v1/auth/login', json={'username': 'viewer', 'password': 'Viewer-test-12345!'}).status_code == 200
    path = f"/api/v1/runs/{old['id']}/recovery"
    assert client.get(path).status_code == 200
    for url in (path, f"/api/v1/recovery-batches/{batch['id']}/cancel"):
        assert client.post(url, json={}, headers={'Idempotency-Key': 'bounded-viewer-denied-001'}).status_code == 403


async def test_http_throttle_retains_body_and_prior_progress_without_accepting_items(client, monkeypatch, tmp_path):
    from extrio.runtime import CrawleeRuntime, _network
    from extrio.source_network import SourceNetworkError, SourceResponse

    store, cid, old = seed(client)

    async def throttled(*args):
        metrics = args[-1]
        metrics['listPagesFetched'] = 2
        network = _network.get()
        network.requests_used = 3
        network.retry_after = 7200
        network.rate_limit_response = SourceResponse('https://example.com/list', 429, {'retry-after': '7200'}, b'Please wait')
        raise SourceNetworkError('source_rate_limited')

    async def progress(*_):
        pass

    monkeypatch.setattr(CrawleeRuntime, '_run', throttled)
    result = await CrawleeRuntime(tmp_path).run(store.get_collector(cid), old, progress)
    assert result.pagination_stop_reason == 'source_rate_limited' and result.items == []
    assert result.coverage_progress == old['coverageProgressBefore'] and not result.coverage_complete
    assert result.source_requests == 3 and result.retry_after_seconds == 7200
    assert (tmp_path / old['id'] / 'attempt_1' / 'document-0-0.html').read_bytes() == b'Please wait'
