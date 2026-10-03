"""唯一的 adapter -> budget -> mediator episode orchestration path。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentbench.live_adapter.errors import ProviderError
from agentbench.live_adapter.openai_responses import ResponsesRequestBuilder
from agentbench.live_adapter.types import ProviderResponse, ResponsesAdapter

from .budget import BudgetConfig, BudgetEnforcer
from .retry import RetryPolicy
from .trajectory import AppendOnlyTrajectory, TrajectoryResult


_TERMINAL = {"completed", "step_budget_exhausted", "tool_budget_exhausted", "output_token_budget_exhausted", "timeout_exhausted", "provider_error", "invalid_function_arguments", "tool_rejected", "incomplete_episode"}


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EpisodeOrchestrator:
    def __init__(self, *, adapter: ResponsesAdapter, request_builder: ResponsesRequestBuilder, mediator: Callable[[str, dict[str, Any]], Any], budget_config: BudgetConfig | None = None, clock: Callable[[], float] | None = None, retry_policy: RetryPolicy | None = None, recorder: AppendOnlyTrajectory | None = None, sleep: Callable[[float], None] | None = None) -> None:
        self.adapter = adapter
        self.request_builder = request_builder
        self.mediator = mediator
        self.budget_config = budget_config or BudgetConfig()
        self.clock = clock
        self.retry_policy = retry_policy or RetryPolicy({"max_retries": 2, "retryable_error_types": ["TransientProviderError", "RateLimitError", "TimeoutError", "ConnectionError"], "non_retryable_error_types": ["AuthenticationError", "InvalidRequestError", "MalformedResponseError"], "backoff_policy": {"type": "none", "initial_seconds": 0, "max_seconds": 0, "sleep": False}})
        self.recorder = recorder or AppendOnlyTrajectory()
        self.sleep = sleep or (lambda _seconds: None)

    def _budget_state(self, budget: BudgetEnforcer) -> dict[str, Any]:
        return {
            "executed_steps": budget.executed_steps,
            "executed_custom_function_calls": budget.executed_custom_function_calls,
            "cumulative_output_tokens": budget.cumulative_output_tokens,
            "remaining_output_token_budget": budget.remaining_output_token_budget,
        }

    def _finish(self, episode_id: str, replicate_id: int, reason: str, budget: BudgetEnforcer) -> TrajectoryResult:
        if reason not in _TERMINAL:
            raise ValueError(f"unknown termination reason: {reason}")
        self.recorder.append({"event_type": "termination", "termination_reason": reason, "budget_state": self._budget_state(budget)})
        return TrajectoryResult(episode_id, replicate_id, reason, tuple(self.recorder.snapshot()), getattr(self.adapter, "calls", 0), 0)

    def _budget_failure(self, budget: BudgetEnforcer) -> str:
        if budget.events and budget.events[-1].get("event") == "timeout_exhausted":
            return "timeout_exhausted"
        if budget.remaining_output_token_budget <= 0:
            return "output_token_budget_exhausted"
        if budget.executed_steps >= budget.config.max_steps:
            return "step_budget_exhausted"
        return "incomplete_episode"

    def run(self, *, episode_id: str, replicate_id: int, agent_visible_context: Any, instructions: str | None = None, evaluator_private_metadata: Mapping[str, Any] | None = None, execution_protocol: str | None = None) -> TrajectoryResult:
        budget = BudgetEnforcer(self.budget_config, clock=self.clock or __import__("time").monotonic)
        input_value = deepcopy(agent_visible_context)
        prompt = instructions if instructions is not None else self.request_builder.system_prompt
        self.recorder.append({"event_type": "episode_start", "episode_id": episode_id, "replicate_id": replicate_id, "agent_visible_context_hash": _hash(agent_visible_context), "evaluator_private_metadata": deepcopy(dict(evaluator_private_metadata or {})), "execution_protocol": execution_protocol})
        while True:
            if budget.check_timeout():
                return self._finish(episode_id, replicate_id, "timeout_exhausted", budget)
            if not budget.admit_step():
                return self._finish(episode_id, replicate_id, self._budget_failure(budget), budget)
            remaining = budget.max_output_tokens_for_next_response()
            if remaining is None:
                return self._finish(episode_id, replicate_id, self._budget_failure(budget), budget)
            request = self.request_builder.build(agent_visible_context=input_value, replicate_id=replicate_id, remaining_output_token_budget=remaining, instructions=prompt)
            request_time = _now()
            self.recorder.append({"event_type": "request", "step_index": budget.executed_steps, "request_metadata_hash": _hash(request["metadata"]), "max_output_tokens": request["max_output_tokens"], "budget_state": self._budget_state(budget)})
            response: ProviderResponse | None = None
            for retry_index in range(self.retry_policy.max_retries + 1):
                try:
                    response = ProviderResponse.from_raw(self.adapter.create_response(request))
                    break
                except BaseException as exc:
                    error_type = str(getattr(exc, "error_type", type(exc).__name__))
                    self.recorder.append({"event_type": "provider_error", "step_index": budget.executed_steps, "error_type": error_type, "retry_index": retry_index})
                    if self.retry_policy.allows(exc, retry_index):
                        self.recorder.append({"event_type": "retry", "step_index": budget.executed_steps, "retry_index": retry_index + 1})
                        self.sleep(0)
                        continue
                    return self._finish(episode_id, replicate_id, "provider_error", budget)
            if response is None:
                return self._finish(episode_id, replicate_id, "provider_error", budget)
            response_time = _now()
            usage = {"input_tokens": int(response.usage.get("input_tokens", 0)), "output_tokens": int(response.usage.get("output_tokens", 0)), "total_tokens": int(response.usage.get("total_tokens", response.usage.get("input_tokens", 0) + response.usage.get("output_tokens", 0)))}
            budget.record_usage(**usage)
            self.recorder.append({"event_type": "provider_response", "step_index": budget.executed_steps, "provider_response": {"id": response.id, "model": response.model, "created_at": response.created_at, "local_request_time_utc": request_time, "local_response_time_utc": response_time}, "usage": usage, "model_output_types": [item.get("type") for item in response.output], "budget_state": self._budget_state(budget)})
            calls = response.function_calls()
            if not calls:
                return self._finish(episode_id, replicate_id, "completed" if response.has_text_output() else "incomplete_episode", budget)
            continuation: list[dict[str, Any]] = []
            for call in calls:
                call_event = {"event_type": "function_call", "step_index": budget.executed_steps, "function_call": {"call_id": call.call_id, "name": call.name, "arguments_hash": _hash(call.arguments)}}
                try:
                    arguments = json.loads(call.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("function arguments must be an object")
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    call_event["error"] = "invalid_function_arguments"
                    self.recorder.append(call_event)
                    return self._finish(episode_id, replicate_id, "invalid_function_arguments", budget)
                allowed, outcome = budget.execute_custom_function(lambda name=call.name, args=arguments: self.mediator(name, args))
                if not allowed:
                    call_event["tool_result"] = {"admitted": False, "blocked": True}
                    self.recorder.append(call_event)
                    return self._finish(episode_id, replicate_id, "tool_budget_exhausted", budget)
                rejected = isinstance(outcome, Mapping) and (outcome.get("admitted") is False or outcome.get("decision") in {"BLOCK", "REJECT"} or outcome.get("status") in {"blocked", "rejected"})
                call_event["tool_result"] = {"admitted": not rejected, "blocked": False, "mediator_result": deepcopy(outcome)}
                self.recorder.append(call_event)
                if rejected:
                    return self._finish(episode_id, replicate_id, "tool_rejected", budget)
                continuation.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(outcome if outcome is not None else {"admitted": True}, ensure_ascii=False, sort_keys=True)})
            input_value = self.request_builder.continuation_input(continuation)
