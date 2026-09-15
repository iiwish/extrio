from types import SimpleNamespace

import pytest

from extrio.adaptive_compile import AdaptiveSession
from extrio.model_budget import BudgetError
from extrio.model_gateway import ModelCompileError, normalize_discovery_plan


def session():
    return AdaptiveSession(SimpleNamespace(provider='custom', model='fixture', limits=None))


def test_region_read_fits_in_one_call_and_expansion_covers_sixteen_children():
    s = session()
    s.register('list-1', 'list', '<main><p>' + '正文 abc ' * 650 + '</p></main>')
    s._envelope('system', {})
    s._read_action({'action': 'read_nodes', 'requests': [{'pageId': 'list-1', 'nodeId': 'n1'}]})
    assert next(iter(s.evidence.values()))['complete']
    s.register('list-2', 'list', '<ul>' + '<li>record</li>' * 13 + '</ul>')
    s._read_action({'action': 'expand_nodes', 'requests': [{'pageId': 'list-2', 'nodeId': 'n1'}]})
    assert list(s.evidence.values())[-1]['complete']


@pytest.mark.asyncio
async def test_discovery_reserves_four_calls_for_compilation():
    s = session()
    assert s.budget.max_calls == 16
    s.budget.calls = 12

    async def call(*_args, **_kwargs):
        s.budget.settle(s.current_reservation, 10, 10)
        return {'action': 'propose_rule', 'rule': {'mode': 'single'}}

    with pytest.raises(BudgetError, match='MODEL_DISCOVERY_BUDGET_EXCEEDED'):
        await s.run(call, 'system', {}, purpose='discover')
    assert s.budget.calls == 12
    await s.run(call, 'system', {}, purpose='compile')
    assert s.budget.calls == 13


@pytest.mark.asyncio
async def test_repeated_complete_read_stops_without_spending_all_calls():
    s = session()
    s.register('list-1', 'list', '<p>data</p>')

    async def call(*_args, **_kwargs):
        s.budget.settle(s.current_reservation, 10, 10)
        return {'action': 'read_nodes', 'requests': [{'pageId': 'list-1', 'nodeId': 'n1'}]}

    with pytest.raises(BudgetError, match='MODEL_NO_PROGRESS'):
        await s.run(call, 'system', {})
    assert s.budget.calls == 4


@pytest.mark.asyncio
async def test_identical_invalid_proposals_stop_across_validation_rounds():
    s = session()

    async def call(*_args, **_kwargs):
        s.budget.settle(s.current_reservation, 10, 10)
        return {'action': 'propose_rule', 'rule': {'mode': 'single'}}

    with pytest.raises(BudgetError, match='MODEL_NO_PROGRESS'):
        for _ in range(8):
            await s.run(call, 'system', {}, purpose='compile')
            s.validate_feedback([{'code': 'FIELD_MISSING', 'field': 'title'}])
    assert s.budget.calls == 4


def test_recovery_does_not_raise_previous_call_limit():
    s = AdaptiveSession(SimpleNamespace(limits=None), prior={'budget': {'calls': 8, 'maxCalls': 8}})
    assert s.budget.max_calls == 8


def test_invalid_discovery_explains_missing_field():
    with pytest.raises(ModelCompileError) as error:
        normalize_discovery_plan({'mode': 'list_detail', 'list': {'fields': {'title': {'selector': 'h1'}}}})
    assert error.value.issues[0]['field'] == 'list.fields.detailUrl'
    assert error.value.issues[0]['reason']


@pytest.mark.asyncio
async def test_changed_proposals_do_not_reset_unchanged_validation_failures():
    s = session()

    async def call(*_args, **_kwargs):
        s.budget.settle(s.current_reservation, 10, 10)
        return {'action': 'propose_rule', 'rule': {'mode': 'single', 'rationale': str(s.budget.calls)}}

    with pytest.raises(BudgetError, match='MODEL_NO_PROGRESS'):
        for _ in range(16):
            await s.run(call, 'system', {}, purpose='compile')
            s.validate_feedback([{'code': 'DETAIL_URL_MISMATCH', 'field': 'detailUrl', 'sample': 1}])
    assert s.budget.calls == 4


def test_resolved_issue_resets_validation_stall_counter():
    s = session()
    first = {'code': 'FIELD_MISSING', 'field': 'title', 'sample': 1}
    second = {'code': 'FIELD_MISSING', 'field': 'content', 'sample': 1}
    for _ in range(3):
        s.validate_feedback([first, second])
    s.validate_feedback([second])
    s.validate_feedback([second])
    s.validate_feedback([])
    assert s.validated


@pytest.mark.asyncio
async def test_new_evidence_allows_further_correction_but_completed_rereads_do_not():
    s = session()
    s.register('list-1', 'list', '<p>fresh evidence</p>')
    issue = {'code': 'FIELD_MISSING', 'field': 'title'}
    for _ in range(3):
        s.validate_feedback([issue])

    async def call(*_args, **_kwargs):
        s.budget.settle(s.current_reservation, 10, 10)
        if s.budget.calls == 1:
            return {'action': 'read_nodes', 'requests': [{'pageId': 'list-1', 'nodeId': 'n1'}]}
        return {'action': 'propose_rule', 'rule': {'mode': 'single'}}

    await s.run(call, 'system', {})
    s.validate_feedback([issue])
    s.validate_feedback([issue])
    s.validate_feedback([issue])
    s._read_action({'action': 'read_nodes', 'requests': [{'pageId': 'list-1', 'nodeId': 'n1'}]})
    with pytest.raises(BudgetError, match='MODEL_NO_PROGRESS'):
        s.validate_feedback([issue])
