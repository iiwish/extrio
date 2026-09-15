import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic


class BudgetError(RuntimeError):
    retryable = False

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ModelLimits:
    context_tokens: int = 32768
    max_input_tokens: int = 32768
    max_output_tokens: int = 4096
    reasoning_tokens: int = 0

    @classmethod
    def from_config(cls, value: dict | None) -> "ModelLimits":
        value = value or {}
        return cls(
            context_tokens=value.get("contextTokens", 32768),
            max_input_tokens=value.get("maxInputTokens", value.get("contextTokens", 32768)),
            max_output_tokens=value.get("maxOutputTokens", 4096),
            reasoning_tokens=value.get("reasoningTokens", 0),
        )

    def input_budget(self, output_tokens: int | None = None) -> int:
        output = self.max_output_tokens if output_tokens is None else output_tokens
        return max(0, min(self.max_input_tokens, self.context_tokens - output - self.reasoning_tokens)
                   - max(256, math.ceil(self.context_tokens * 0.05)))


def count_tokens(messages: list[dict], *, provider: str, model: str) -> tuple[int, str]:
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if provider == "openai":
        try:
            import tiktoken
            encoder = tiktoken.encoding_for_model(model)
            # Message framing and model/API revisions are not fully described by the tokenizer.
            return math.ceil(len(encoder.encode(serialized, disallowed_special=())) * 1.1) + 64, "tiktoken_with_margin"
        except (ImportError, KeyError):
            pass
    return len(serialized.encode("utf-8")) + 64, "utf8_upper_estimate"


@dataclass
class Reservation:
    input_tokens: int
    output_tokens: int
    settled: bool = False


class TaskBudget:
    def __init__(
        self, limits: ModelLimits, *, max_calls: int = 16, max_input_tokens: int = 120000,
        max_output_tokens: int = 16000, max_seconds: float = 240, clock: Callable[[], float] = monotonic,
    ):
        self.limits = limits
        self.max_calls = max_calls
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_seconds = max_seconds
        self.clock = clock
        self.started = clock()
        self.started_at = datetime.now(UTC).isoformat()
        self.calls = 0
        self.input_used = 0
        self.output_used = 0
        self.token_method = "utf8_upper_estimate"
        self.stop_reason: str | None = None

    def fail(self, code: str):
        self.stop_reason = code
        raise BudgetError(code)

    def check(self) -> None:
        self.check_consumption()
        if self.calls >= self.max_calls:
            self.fail("MODEL_CALL_BUDGET_EXCEEDED")

    def check_consumption(self) -> None:
        if self.remaining_seconds() <= 0:
            self.fail("MODEL_TIME_BUDGET_EXCEEDED")
        if self.input_used > self.max_input_tokens or self.output_used > self.max_output_tokens:
            self.fail("MODEL_TOKEN_BUDGET_EXCEEDED")

    def remaining_seconds(self) -> float:
        return max(0, self.max_seconds - (self.clock() - self.started))

    def reserve(self, input_tokens: int, output_tokens: int) -> Reservation:
        self.check()
        if output_tokens < 1 or output_tokens > self.limits.max_output_tokens:
            self.fail("MODEL_OUTPUT_BUDGET_EXCEEDED")
        if input_tokens < 0 or input_tokens > self.limits.input_budget(output_tokens):
            self.fail("MODEL_CONTEXT_INSUFFICIENT")
        if self.input_used + input_tokens > self.max_input_tokens or self.output_used + output_tokens > self.max_output_tokens:
            self.fail("MODEL_TOKEN_BUDGET_EXCEEDED")
        self.calls += 1
        self.input_used += input_tokens
        self.output_used += output_tokens
        return Reservation(input_tokens, output_tokens)

    def settle(self, reservation: Reservation, input_tokens: int | None, output_tokens: int | None) -> None:
        if reservation.settled:
            return
        reservation.settled = True
        if isinstance(input_tokens, int) and input_tokens >= 0:
            self.input_used += input_tokens - reservation.input_tokens
        if isinstance(output_tokens, int) and output_tokens >= 0:
            self.output_used += output_tokens - reservation.output_tokens

    def summary(self) -> dict:
        return {
            "calls": self.calls, "maxCalls": self.max_calls, "inputTokens": self.input_used,
            "outputTokens": self.output_used, "maxInputTokens": self.max_input_tokens,
            "maxOutputTokens": self.max_output_tokens, "contextTokens": self.limits.context_tokens,
            "tokenMethod": self.token_method, "elapsedSeconds": round(self.clock() - self.started, 2),
            "maxSeconds": self.max_seconds, "stopReason": self.stop_reason,
            "startedAt": self.started_at,
        }
