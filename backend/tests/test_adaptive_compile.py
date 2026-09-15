import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from extrio.adaptive_compile import AdaptiveSession
from extrio.credentials import CredentialCipher
from extrio.model_budget import BudgetError
from extrio.model_gateway import ActiveModel, ModelRuleCompiler
from extrio.store import Store


def model(window=16384):
    return SimpleNamespace(provider="custom", model="fixture", limits={"contextTokens": window, "maxOutputTokens": 1024})


async def metered(session, action):
    session.budget.settle(session.current_reservation, 100, 40)
    return action


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [8192, 16384, 32768, 131072])
async def test_model_selects_tail_node_across_bounded_rounds(window):
    session = AdaptiveSession(model(window))
    session.register("detail-1", "detail", '<body><nav>' + '<a href="/">Navigation</a>' * 300
                     + '</nav><article id="body">Real正文</article></body>')
    page = session.pages["detail-1"]
    article = next(n for n in page.nodes.values() if n.tag == "article")
    payloads = []

    async def call(_model, _system, evidence, **_kwargs):
        payloads.append(evidence)
        if len(payloads) == 1:
            return await metered(session, {"action": "read_nodes", "requests": [{"pageId": "detail-1", "nodeId": article.id}]})
        assert "Real正文" in str(evidence["evidence"])
        return await metered(session, {"action": "propose_rule", "rule": {"list": {"fields": {"content": "#body"}}}})

    result = await session.run(call, "Compile within the contract", {"expectedFields": [{"key": "content"}]})
    assert result["list"]["fields"]["content"] == "#body"
    assert session.budget.calls == 2
    assert len(payloads[1]["evidence"]) == 1
    assert all(p["expectedFields"] == [{"key": "content"}] for p in payloads)
    assert "Real正文" not in str(session.summary())


@pytest.mark.asyncio
async def test_invalid_actions_are_bounded_and_cannot_read_files_or_other_pages():
    session = AdaptiveSession(model())
    session.register("list-1", "list", "<p>Data</p>")

    async def call(*_args, **_kwargs):
        return await metered(session, {"action": "read_nodes", "requests": [{"pageId": "/etc/passwd", "nodeId": "n0"}]})

    with pytest.raises(BudgetError, match="NO_PROGRESS"):
        await session.run(call, "safe", {})
    assert session.budget.calls == 3
    assert not session.reads


@pytest.mark.asyncio
async def test_cancellation_prevents_later_calls():
    session = AdaptiveSession(model())
    session.register("list-1", "list", "<p>Data</p>")
    entered = asyncio.Event()

    async def call(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(session.run(call, "safe", {}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.budget.calls == 1
    assert session.budget.input_used > 0


@pytest.mark.asyncio
async def test_contract_too_large_fails_without_network():
    session = AdaptiveSession(model(4096))

    async def call(*_args, **_kwargs):
        pytest.fail("must not send oversized contract")

    with pytest.raises(BudgetError, match="CONTEXT"):
        await session.run(call, "system", {"contract": "x" * 20000})
    assert session.budget.calls == 0


@pytest.mark.asyncio
async def test_recovery_counts_downtime_against_task_time_limit():
    prior = {"budget": {"calls": 1, "elapsedSeconds": 2,
                        "startedAt": (datetime.now(UTC) - timedelta(seconds=250)).isoformat()}}
    session = AdaptiveSession(model(), prior=prior)
    with pytest.raises(BudgetError, match="TIME"):
        await session.run(None, "system", {})
    assert session.budget.calls == 1


@pytest.mark.asyncio
async def test_context_rejection_reduces_input_without_cutting_contract():
    from extrio.adaptive_compile import ContextRejected
    session = AdaptiveSession(model(32768))
    session.register("list-1", "list", "<main>" + "x" * 6000 + "</main>")
    session._read_action({"action": "read_nodes", "requests": [{"pageId": "list-1", "nodeId": "n0"}]})
    sizes = []

    async def call(_model, system, evidence, **_kwargs):
        assert evidence["contract"] == {"identity": ["id"]}
        sizes.append(session._count(system, evidence))
        if len(sizes) < 4:
            raise ContextRejected()
        return {"action": "propose_rule", "rule": {"mode": "single"}}

    await session.run(call, "system", {"contract": {"identity": ["id"]}})
    assert session.budget.calls == 4
    assert session.budget.input_used == sum(sizes)
    assert session.context_scale < 0.4


@pytest.mark.asyncio
async def test_lost_ownership_during_reservation_never_calls_model():
    async def report(_summary):
        raise RuntimeError("lease lost")
    session = AdaptiveSession(model(), report=report)

    async def call(*_args, **_kwargs):
        pytest.fail("model must not be called without ownership")

    with pytest.raises(RuntimeError, match="lease lost"):
        await session.run(call, "system", {})
    assert session.budget.calls == 1


@pytest.mark.asyncio
async def test_reproposal_keeps_selected_reads_and_previous_candidate_as_application_state():
    session = AdaptiveSession(model())
    session.register('detail-1', 'detail', '<article id="body">Actual content</article>')
    session._read_action({'action': 'read_nodes', 'requests': [{'pageId': 'detail-1', 'nodeId': 'n1'}]})
    proposal = {'mode': 'single', 'list': {'fields': {'content': '#wrong'}}}

    async def first(*_args, **_kwargs):
        return await metered(session, {'action': 'propose_rule', 'rule': proposal})

    await session.run(first, 'system', {})
    session.validate_feedback([{'code': 'FIELD_MISSING', 'field': 'content', 'sample': 1}])

    async def second(_model, _system, evidence, **_kwargs):
        assert evidence['previousProposal'] == proposal
        assert evidence['readState'][0]['nodeId'] == 'n1'
        assert evidence['validationFeedback'][0]['code'] == 'FIELD_MISSING'
        assert 'Actual content' in str(evidence['evidence'])
        return await metered(session, {'action': 'propose_rule', 'rule': {'mode': 'single'}})

    await session.run(second, 'system', {})
    assert 'Actual content' not in str(session.summary())


def test_diagnostic_summary_matches_api_schema_and_omits_feedback_text():
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
    session = AdaptiveSession(model())
    session.register('detail-1', 'detail', '<h1>Secret page title</h1>')
    session.validate_feedback([{'code': 'TITLE_MISMATCH', 'field': 'title', 'sample': 1,
                               'expectedTitle': 'Secret page title', 'actualTitle': 'Wrong title'}])
    summary = session.summary()
    document = yaml.safe_load((Path(__file__).resolve().parents[2] / 'docs/contracts/openapi.yaml').read_text())
    Draft202012Validator({'$ref': '#/components/schemas/AdaptiveEvidenceSummary',
                         'components': document['components']}, format_checker=FormatChecker()).validate(summary)
    assert 'Secret page title' not in str(summary) and 'Wrong title' not in str(summary)


@pytest.mark.asyncio
async def test_small_window_returns_all_requested_sample_fragments_not_only_last_page():
    session = AdaptiveSession(model(16384))
    for number in range(1, 4):
        session.register(f'detail-{number}', 'detail', '<div>' * 8 + '<table><tr><td>'
                         + '正文 content ' * 500 + '</td></tr></table>' + '</div>' * 8)
    calls = []

    async def call(_model, _system, evidence, **_kwargs):
        calls.append(evidence)
        if len(calls) == 1:
            requests = [{'pageId': hint['pageId'], 'nodeId': next(node['nodeId'] for node in hint['nodes'] if node['tag'] == 'table')}
                        for hint in evidence['directoryHints']]
            return await metered(session, {'action': 'read_nodes', 'requests': requests})
        assert {read['pageId'] for read in evidence['evidence']} == {'detail-1', 'detail-2', 'detail-3'}
        return await metered(session, {'action': 'propose_rule', 'rule': {'mode': 'single'}})

    await session.run(call, 'system', {'fixedContract': 'x' * 7000})
    assert session.budget.calls == 2


@pytest.mark.asyncio
async def test_task_token_exhaustion_is_not_reported_as_model_context_failure():
    session = AdaptiveSession(model())
    session.budget.max_input_tokens = 100
    with pytest.raises(BudgetError, match='MODEL_TOKEN_BUDGET_EXCEEDED'):
        await session.run(None, 'system', {})
    assert session.budget.calls == 0


@pytest.mark.asyncio
async def test_budget_is_shared_between_discovery_and_compilation_and_attempts():
    session = AdaptiveSession(model())

    async def call(*_args, **_kwargs):
        return await metered(session, {"action": "propose_rule", "rule": {"list": {}, "revision": session.budget.calls}})

    for _ in range(16):
        await session.run(call, "system", {})
    retried = AdaptiveSession(model(), prior=session.summary())
    with pytest.raises(BudgetError, match="CALL"):
        await retried.run(call, "system", {})


@pytest.mark.asyncio
async def test_real_gateway_drives_node_reads_and_charges_provider_usage(tmp_path: Path, monkeypatch):
    compiler = ModelRuleCompiler(Store(tmp_path / "fixture.db"), CredentialCipher(tmp_path / "key"))
    monkeypatch.setattr(compiler, "_model", lambda: ActiveModel("custom", "https://fixture.test", "fixture", "secret"))
    sent = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, _url, *, json: dict, **_kwargs):
            sent.append(json)
            action = ({"action": "read_nodes", "requests": [{"pageId": "list-1", "nodeId": "n0"}]}
                      if len(sent) == 1 else {"action": "propose_rule", "rule": {
                          "mode": "single", "transport": "http", "list": {"itemsSelector": "main",
                          "fields": {"title": {"selector": "h1::text"}}, "pagination": {"type": "none"}}}})
            response = {"choices": [{"message": {"content": __import__("json").dumps(action)}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 150, "completion_tokens": 50}}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: response)

    monkeypatch.setattr("extrio.model_gateway.httpx.AsyncClient", Client)
    with compiler.task_session() as session:
        result = await compiler.discover({}, "https://example.com", "<main><h1>Actual</h1></main>")
        assert result["mode"] == "single"
        assert session.budget.calls == 2 and session.budget.input_used == 300
        assert session.budget.output_used == 100
    second_input = json.loads(sent[1]["messages"][1]["content"])
    assert "Actual" in str(second_input["evidence"])
    assert "domEvidence" not in second_input
