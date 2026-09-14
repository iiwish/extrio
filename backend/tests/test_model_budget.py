import pytest

from extrio.model_budget import BudgetError, ModelLimits, TaskBudget, count_tokens


@pytest.mark.parametrize("window", [8192, 16384, 32768, 131072])
def test_context_budget_accounts_for_output_reasoning_and_margin(window):
    limits = ModelLimits(context_tokens=window, max_input_tokens=window, max_output_tokens=2048, reasoning_tokens=512)
    assert limits.input_budget() < window - 2048 - 512
    budget = TaskBudget(limits, max_input_tokens=window)
    reservation = budget.reserve(limits.input_budget(), 2048)
    assert reservation.input_tokens + reservation.output_tokens + limits.reasoning_tokens < window
    with pytest.raises(BudgetError, match="CONTEXT"):
        budget.reserve(limits.input_budget() + 1, 2048)


def test_limits_enforce_independent_input_and_output_caps():
    limits = ModelLimits(context_tokens=32768, max_input_tokens=4096, max_output_tokens=1024)
    budget = TaskBudget(limits)
    assert limits.input_budget() <= 4096
    with pytest.raises(BudgetError):
        budget.reserve(100, 1025)


def test_missing_usage_is_charged_and_call_count_includes_failed_calls():
    budget = TaskBudget(ModelLimits(), max_calls=2)
    first = budget.reserve(200, 100)
    budget.settle(first, None, None)
    second = budget.reserve(200, 100)
    budget.settle(second, 50, 25)
    assert budget.input_used == 250 and budget.output_used == 125
    with pytest.raises(BudgetError, match="CALL"):
        budget.reserve(1, 1)


def test_timeout_and_total_budget_stop_before_call():
    clock = [0.0]
    budget = TaskBudget(ModelLimits(), clock=lambda: clock[0], max_seconds=5, max_input_tokens=100)
    with pytest.raises(BudgetError, match="TOKEN"):
        budget.reserve(101, 1)
    assert budget.calls == 0
    clock[0] = 6
    with pytest.raises(BudgetError, match="TIME"):
        budget.reserve(1, 1)


def test_unknown_model_uses_conservative_byte_estimate():
    count, method = count_tokens([{"role": "user", "content": "中文 mixed"}], provider="custom", model="unknown")
    assert count >= len("中文 mixed".encode())
    assert method == "utf8_upper_estimate"


def test_reported_overspend_cannot_be_accepted_as_a_final_proposal():
    budget = TaskBudget(ModelLimits(), max_input_tokens=100)
    reserved = budget.reserve(80, 20)
    budget.settle(reserved, 101, 10)
    with pytest.raises(BudgetError, match='TOKEN'):
        budget.check_consumption()
