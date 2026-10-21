"""Finite, explicitly authorized continuation, independent of source schedules."""

import copy
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from extrio.collection_workflows import finish_command, lock_collector, receipt
from extrio.collector_lifecycle import LifecycleError, require_active, source_execution_digest
from extrio.coverage import valid_progress
from extrio.store import payload_hash, stable_id

ACTIVE = ('cooling_down', 'running', 'cancelling')
DELAYS = (1800, 7200, 21600)
REQUEST_LIMIT = 120
CONTROL_LOCK = 738462901337


class RecoveryError(LifecycleError):
    pass


def iso(value):
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def lock_control(store, connection, *, wait=True):
    if store.dialect.name == 'postgresql':
        if wait:
            connection.execute('SELECT pg_advisory_xact_lock(?)', (CONTROL_LOCK,))
        elif not connection.execute('SELECT pg_try_advisory_xact_lock(?) AS locked', (CONTROL_LOCK,)).fetchone()['locked']:
            raise RecoveryError('SOURCE_RECOVERY_ACTIVE')


def get(store, identifier, connection=None):
    if connection is None:
        with store.connect() as connection:
            return get(store, identifier, connection)
    return store._decode(connection.execute('SELECT data FROM recovery_batches WHERE id=?', (identifier,)).fetchone())


def for_run(store, run_id, connection=None):
    if connection is None:
        with store.connect() as connection:
            return for_run(store, run_id, connection)
    run = store.get_run(run_id, connection)
    if run and run.get('recoveryBatchId'):
        return get(store, run['recoveryBatchId'], connection)
    return store._decode(connection.execute('SELECT data FROM recovery_batches WHERE seed_run_id=?', (run_id,)).fetchone())


def public(batch):
    if batch is None:
        return None
    keys = ('id', 'collectorId', 'seedRunId', 'status', 'reason', 'createdAt', 'updatedAt', 'expiresAt', 'finishedAt',
        'nextAttemptAt', 'maxAttempts', 'attemptRunIds', 'activeRunId', 'reservedRequests', 'maxRequests',
        'requestsPerAttempt', 'maxPages', 'maxItems', 'cooldownSeconds', 'windowStart', 'ruleVersion', 'policyVersion', 'cancelRequested')
    return {**{key: batch[key] for key in keys}, 'resumePage': batch['expectedProgress']['pageIndex'] + 1}


def active(store, connection):
    return [store._decode(row) for row in connection.execute(
        "SELECT data FROM recovery_batches WHERE status IN ('cooling_down','running','cancelling') ORDER BY created_at"
    ).fetchall()]


def hosts(store, source, connection):
    rule = store.get_rule_version(source.get('activeRuleVersion', ''), connection)
    allowed = (rule or {}).get('gatherSpec', {}).get('sourceContext', {}).get('allowedHosts', [])
    return sorted({host.lower().rstrip('.') for host in [*allowed, urlsplit(source['sourceUrl']).hostname] if host})


def guard_source_work(store, connection, source, owner=None):
    # Nonblocking acquisition avoids reversing existing collector/job lock order.
    lock_control(store, connection, wait=False)
    rows = connection.execute("SELECT data FROM recovery_batches WHERE status IN ('cooling_down','running','cancelling') "
                              'OR hold_until > ?', (iso(datetime.now(UTC)),)).fetchall()
    for row in rows:
        batch = store._decode(row)
        if set(batch['hosts']).intersection(hosts(store, source, connection)) and batch['id'] != owner:
            raise RecoveryError('SOURCE_RECOVERY_ACTIVE')


def context(source):
    return payload_hash({'source': source_execution_digest(source), 'policy': source.get('collectionPolicy'),
                         'collectionVersion': source.get('collectionVersion'), 'lifecycle': source.get('lifecycle', 'active')})


def finished(run, fallback):
    if run.get('finishedAtIso'):
        return instant(run['finishedAtIso'])
    duration = re.fullmatch(r'(\d+(?:\.\d+)?)s', run.get('duration', ''))
    if duration and run.get('startedAtIso'):
        return instant(run['startedAtIso']) + timedelta(seconds=float(duration[1]))
    return fallback


def save(store, connection, batch, now):
    batch['updatedAt'] = iso(now)
    connection.execute('UPDATE recovery_batches SET status=?, hold_until=?, data=?, updated_at=? WHERE id=?',
                       (batch['status'], batch.get('sourceNotBefore'), store.dialect.json_param(batch), batch['updatedAt'], batch['id']))


def stop(batch, reason, now, *, status='needs_attention'):
    batch.update(status=status, reason=reason, nextAttemptAt=None, finishedAt=iso(now))


def cool(batch, run, now):
    index = len(batch['attemptRunIds'])
    delay = max(DELAYS[min(index, len(DELAYS) - 1)], run.get('retryAfterSeconds') or 0)
    due = finished(run, now) + timedelta(seconds=delay)
    batch['sourceNotBefore'] = iso(due)
    if index >= batch['maxAttempts']:
        stop(batch, 'attempt_limit', now)
        return
    if due >= instant(batch['expiresAt']):
        stop(batch, 'server_wait_exceeds_deadline', now)
        return
    batch.update(status='cooling_down', reason='source_rate_limited', nextAttemptAt=iso(due))


def start(store, run_id, key, audit, *, now=None):
    now = now or datetime.now(UTC)
    scope, body = f'POST:/runs/{run_id}/recovery', {}
    with store.transaction() as connection:
        lock_control(store, connection)
        if found := receipt(store, connection, scope, key, body):
            return found
        if for_run(store, run_id, connection):
            raise RecoveryError('RECOVERY_ALREADY_EXISTS')
        run = store.get_run(run_id, connection)
        if not run:
            raise RecoveryError('RUN_NOT_FOUND')
        lock_collector(store, connection, run['collectorId'])
        source = store.get_collector(run['collectorId'], connection)
        require_active(source)
        progress = source.get('coverageProgress')
        policy = source.get('collectionPolicy') or {}
        if (source.get('status') != 'published' or source.get('latestRunId') != run_id
                or source.get('schedule', {}).get('enabled') or source.get('activeOperationId')
                or source.get('pendingCollectionVersion') or store.has_active_run(source['id'], connection)
                or run.get('paginationStopReason') != 'source_rate_limited' or run['status'] != 'failed'
                or run.get('integrityStatus') != 'verified' or run['ruleVersion'] != source['activeRuleVersion']
                or run['policyVersion'] != policy.get('id') or policy.get('checkpointMode') != 'observed'
                or not valid_progress(progress, run['ruleDigest'], policy.get('id'))
                or progress != run.get('coverageProgressAfter') or progress != run.get('coverageProgressBefore')
                or run.get('checkpointAfter') or run.get('items') or policy['maxPages'] > 3 or policy['maxItems'] > 50):
            raise RecoveryError('RECOVERY_SEED_INVALID')
        from extrio.config import get_settings
        from extrio.contracts import ContractBundle
        from extrio.integrity import IntegrityError, verify_rule_attestation

        rule = store.get_rule_version(source['activeRuleVersion'], connection)
        attestation = store.latest_rule_attestation(source['activeRuleVersion'], connection)
        signing_key = store.get_signing_key(attestation['keyId'], connection) if attestation else None
        try:
            if not rule or not attestation or not signing_key:
                raise IntegrityError('Recovery rule proof missing')
            verified = verify_rule_attestation(spec=rule['gatherSpec'], attestation=attestation, signing_key=signing_key,
                contracts=ContractBundle(get_settings().contracts_path), expected_rule_version_id=rule['id'],
                expected_tenant_id=rule['tenantId'])
            if verified['ruleDigest'] != run['ruleDigest']:
                raise IntegrityError('Recovery seed digest changed')
        except IntegrityError as exc:
            raise RecoveryError('RECOVERY_SEED_INVALID') from exc
        guard_source_work(store, connection, source)
        batch_hosts = hosts(store, source, connection)
        # Do not adopt or compete with an already queued/running source task.
        for row in connection.execute("SELECT DISTINCT o.collector_id FROM jobs j JOIN operations o ON o.id=j.operation_id "
                                      "WHERE j.status IN ('queued','processing') AND j.kind IN ('run','explore')").fetchall():
            other = store.get_collector(row['collector_id'], connection)
            if other and set(batch_hosts).intersection(hosts(store, other, connection)):
                raise RecoveryError('SOURCE_RECOVERY_ACTIVE')
        batch = {'id': stable_id('recovery'), 'collectorId': source['id'], 'seedRunId': run_id,
            'status': 'cooling_down', 'reason': 'source_rate_limited', 'createdAt': iso(now), 'updatedAt': iso(now),
            'expiresAt': iso(now + timedelta(hours=24)), 'finishedAt': None, 'nextAttemptAt': None,
            'maxAttempts': 3, 'attemptRunIds': [], 'activeRunId': None, 'reservedRequests': 0,
            'maxRequests': 360, 'requestsPerAttempt': REQUEST_LIMIT, 'maxPages': 3, 'maxItems': 50,
            'cooldownSeconds': list(DELAYS), 'hosts': batch_hosts, 'contextDigest': context(source),
            'expectedProgress': copy.deepcopy(progress), 'expectedCheckpoint': store.get_checkpoint(source['id'], connection),
            'ruleVersion': run['ruleVersion'], 'ruleDigest': run['ruleDigest'], 'policyVersion': run['policyVersion'],
            'windowStart': progress['windowStart'], 'cancelRequested': False}
        cool(batch, run, now)
        connection.execute('INSERT INTO recovery_batches(id,seed_run_id,collector_id,status,hold_until,data,created_at,updated_at) '
                           'VALUES(?,?,?,?,?,?,?,?)',
            (batch['id'], run_id, source['id'], batch['status'], batch.get('sourceNotBefore'),
             store.dialect.json_param(batch), batch['createdAt'], batch['updatedAt']))
        return finish_command(store, connection, scope, key, body, batch, 201, audit, 'recovery_batch', batch['id'], 'recovery.start')


def request_stop(store, identifier, key, audit, *, now=None):
    now = now or datetime.now(UTC)
    scope, body = f'POST:/recovery-batches/{identifier}/cancel', {}
    with store.transaction() as connection:
        lock_control(store, connection)
        if found := receipt(store, connection, scope, key, body):
            return found
        batch = get(store, identifier, connection)
        if not batch:
            raise RecoveryError('RECOVERY_NOT_FOUND')
        if batch['status'] in ACTIVE:
            batch['cancelRequested'] = True
            if batch['activeRunId']:
                run = store.get_run(batch['activeRunId'], connection)
                operation = store.get_operation(run['operationId'], connection)
                if operation['status'] not in {'succeeded', 'failed', 'cancelled', 'timed_out'}:
                    operation['cancelRequested'] = True
                    store.save_operation(operation, batch['collectorId'], connection)
                batch.update(status='cancelling', reason='cancel_requested', nextAttemptAt=None)
            else:
                stop(batch, 'cancel_requested', now, status='cancelled')
            save(store, connection, batch, now)
        return finish_command(store, connection, scope, key, body, batch, 200, audit, 'recovery_batch', identifier, 'recovery.cancel')


def continuation_verified(store, connection, source, batch, run):
    if (run['status'] not in {'succeeded', 'partially_succeeded'}
            or run['paginationStopReason'] not in {'max_pages', 'max_items', 'checkpoint_reached', 'time_window_reached'}
            or run['listPagesFetched'] > 3 or run['detailPagesFetched'] > 50 or len(run['items']) > 50
            or (run.get('sourceRequests') or 0) > REQUEST_LIMIT):
        return False
    after = run.get('coverageProgressAfter')
    checkpoint = run.get('checkpointAfter')
    if checkpoint:
        return (checkpoint.get('kind') == 'coverage' and checkpoint.get('policyVersionId') == batch['policyVersion']
                and checkpoint.get('ruleDigest') == batch['ruleDigest']
                and store.get_checkpoint(source['id'], connection) == checkpoint and not source.get('coverageProgress'))
    return (valid_progress(after, batch['ruleDigest'], batch['policyVersion']) and after['windowStart'] == batch['windowStart']
            and after != batch['expectedProgress'] and after == source.get('coverageProgress')
            and after['pageIndex'] >= batch['expectedProgress']['pageIndex']
            and (urlsplit(after['resumeUrl']).hostname or '').lower() in batch['hosts'])


def tick(store, create_run, *, now=None):
    now = now or datetime.now(UTC)
    dispatched = 0
    with store.transaction() as connection:
        lock_control(store, connection)
        for batch in active(store, connection):
            try:
                lock_collector(store, connection, batch['collectorId'])
            except LifecycleError:
                stop(batch, 'source_unavailable', now)
                save(store, connection, batch, now)
                continue
            source = store.get_collector(batch['collectorId'], connection)
            if batch['activeRunId']:
                run = store.get_run(batch['activeRunId'], connection)
                if run['status'] in {'queued', 'running', 'finalizing'}:
                    if now >= instant(batch['expiresAt']) or batch['cancelRequested']:
                        operation = store.get_operation(run['operationId'], connection)
                        operation['cancelRequested'] = True
                        store.save_operation(operation, source['id'], connection)
                        batch.update(status='cancelling', reason='cancel_requested' if batch['cancelRequested'] else 'deadline_reached')
                        save(store, connection, batch, now)
                    continue
                batch['activeRunId'] = None
                if batch['status'] == 'cancelling':
                    stop(batch, batch['reason'], now, status='cancelled' if batch['cancelRequested'] else 'needs_attention')
                elif context(source) != batch['contextDigest'] or source['schedule']['enabled']:
                    stop(batch, 'context_changed', now)
                elif (run['coverageProgressBefore'] != batch['expectedProgress']
                      or run['checkpointBefore'] != batch['expectedCheckpoint'] or run['integrityStatus'] != 'verified'
                      or run['ruleVersion'] != batch['ruleVersion'] or run['policyVersion'] != batch['policyVersion']
                      or run['ruleDigest'] != batch['ruleDigest']):
                    stop(batch, 'context_changed', now)
                elif run['paginationStopReason'] == 'source_rate_limited':
                    if (run.get('items') or run.get('checkpointAfter') or run.get('coverageProgressAfter') != batch['expectedProgress']
                            or source.get('coverageProgress') != batch['expectedProgress']):
                        stop(batch, 'progress_changed', now)
                    else:
                        cool(batch, run, now)
                elif continuation_verified(store, connection, source, batch, run):
                    batch['sourceNotBefore'] = None
                    stop(batch, 'continuation_verified', now, status='recovered')
                else:
                    stop(batch, 'run_not_recoverable', now)
                save(store, connection, batch, now)
            if batch['status'] != 'cooling_down':
                continue
            if now >= instant(batch['expiresAt']):
                stop(batch, 'deadline_reached', now)
            elif context(source) != batch['contextDigest'] or source['schedule']['enabled']:
                stop(batch, 'context_changed', now)
            elif (source.get('coverageProgress') != batch['expectedProgress']
                  or store.get_checkpoint(source['id'], connection) != batch['expectedCheckpoint']):
                stop(batch, 'progress_changed', now)
            elif now >= instant(batch['nextAttemptAt']):
                if len(batch['attemptRunIds']) >= batch['maxAttempts'] or batch['reservedRequests'] + REQUEST_LIMIT > batch['maxRequests']:
                    stop(batch, 'attempt_limit', now)
                else:
                    try:
                        operation = create_run(source['id'], connection, recovery_batch_id=batch['id'], request_limit=REQUEST_LIMIT)
                    except (ValueError, RuntimeError):
                        stop(batch, 'dispatch_rejected', now)
                    else:
                        batch['activeRunId'] = operation['resourceId']
                        batch['attemptRunIds'].append(operation['resourceId'])
                        batch['reservedRequests'] += REQUEST_LIMIT
                        batch.update(status='running', nextAttemptAt=None, reason='continuation_running')
                        dispatched += 1
            save(store, connection, batch, now)
    return dispatched


def validate_attempt(store, run):
    if not run.get('recoveryBatchId'):
        return
    with store.connect() as connection:
        batch = get(store, run['recoveryBatchId'], connection)
        source = store.get_collector(run['collectorId'], connection)
        if (not batch or batch['status'] != 'running' or batch['activeRunId'] != run['id'] or batch['cancelRequested']
                or datetime.now(UTC) >= instant(batch['expiresAt']) or not source
                or (batch.get('sourceNotBefore') and datetime.now(UTC) < instant(batch['sourceNotBefore']))
                or context(source) != batch['contextDigest'] or source['schedule']['enabled']
                or source.get('coverageProgress') != batch['expectedProgress']
                or store.get_checkpoint(source['id'], connection) != batch['expectedCheckpoint']):
            raise RecoveryError('RECOVERY_ATTEMPT_BLOCKED')
