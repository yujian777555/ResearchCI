"""Runner-side episode budget semantics; no provider or network calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class BudgetConfig:
    max_steps: int = 30
    max_custom_function_calls: int = 20
    timeout_seconds: int = 900
    cumulative_output_token_budget: int = 16000
    provider_per_response_output_limit: int = 128000


@dataclass
class BudgetEnforcer:
    config: BudgetConfig = field(default_factory=BudgetConfig)
    clock: Callable[[], float] = __import__("time").monotonic
    started_at: float = field(init=False)
    executed_steps: int = 0
    executed_custom_function_calls: int = 0
    cumulative_output_tokens: int = 0
    cumulative_input_tokens: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    @property
    def remaining_output_token_budget(self) -> int:
        return max(0, self.config.cumulative_output_token_budget - self.cumulative_output_tokens)

    def _timeout(self) -> bool:
        if self.clock() - self.started_at >= self.config.timeout_seconds:
            self.events.append({"event": "timeout_exhausted", "elapsed_seconds": self.clock() - self.started_at})
            return True
        return False

    def admit_step(self) -> bool:
        if self._timeout():
            return False
        if self.executed_steps >= self.config.max_steps:
            self.events.append({"event": "step_budget_exhausted", "executed_steps": self.executed_steps, "attempted_step_index": self.executed_steps + 1})
            return False
        self.executed_steps += 1
        return True

    def execute_custom_function(self, executor: Callable[[], Any]) -> tuple[bool, Any]:
        if self._timeout():
            return False, None
        attempted = self.executed_custom_function_calls + 1
        if self.executed_custom_function_calls >= self.config.max_custom_function_calls:
            self.events.append({"event": "tool_budget_exhausted", "executed_custom_function_calls": self.executed_custom_function_calls, "attempted_call_index": attempted})
            return False, None
        self.executed_custom_function_calls += 1
        return True, executor()

    def max_output_tokens_for_next_response(self) -> int | None:
        if self._timeout():
            return None
        remaining = self.remaining_output_token_budget
        if remaining <= 0:
            self.events.append({"event": "output_token_budget_exhausted", "cumulative_output_tokens": self.cumulative_output_tokens})
            return None
        return min(self.config.provider_per_response_output_limit, remaining)

    def record_usage(self, *, input_tokens: int, output_tokens: int, total_tokens: int | None = None) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token usage cannot be negative")
        self.cumulative_input_tokens += input_tokens
        self.cumulative_output_tokens += output_tokens
        self.events.append({"event": "response_usage", "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens if total_tokens is not None else input_tokens + output_tokens, "cumulative_output_tokens": self.cumulative_output_tokens})

    def metadata(self) -> dict[str, Any]:
        return {"executed_steps": self.executed_steps, "executed_custom_function_calls": self.executed_custom_function_calls, "cumulative_input_tokens": self.cumulative_input_tokens, "cumulative_output_tokens": self.cumulative_output_tokens, "remaining_output_token_budget": self.remaining_output_token_budget, "events": list(self.events)}
