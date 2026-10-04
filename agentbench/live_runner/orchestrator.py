"""唯一的 adapter -> budget -> mediator episode orchestration path。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from agentbench.live_adapter.openai_responses import ResponsesRequestBuilder
from agentbench.live_adapter.tool_schemas import ToolSchemaValidationError
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
    """所有 provider cycle 与 custom function 都必须经过本路径的预算门。"""

    def __init__(self, *, adapter: ResponsesAdapter, request_builder: ResponsesRequestBuilder, mediator: Callable[[str, dict[str, Any]], Any], budget_config: BudgetConfig | None = None, clock: Callable[[], float] | None = None, retry_policy: RetryPolicy | None = None, recorder: AppendOnlyTrajectory | None = None, sleep: Callable[[float], None] | None = None) -> None:
        self.adapter = adapter
        self.request_builder = request_builder
        self.mediator = mediator
        self.budget_config = budget_config or BudgetConfig()
        self.clock = clock or time.monotonic
        self.retry_policy = retry_policy or RetryPolicy.from_file(request_builder.root / "agentbench/live_protocol/retry_policy.json")
        self.recorder = recorder or AppendOnlyTrajectory()
        self.sleep = sleep if sleep is not None else time.sleep

    def _budget_state(self, budget: BudgetEnforcer) -> dict[str, Any]:
        return {
            "executed_steps": budget.executed_steps,
            "executed_custom_function_calls": budget.executed_custom_function_calls,
            "cumulative_output_tokens": budget.cumulative_output_tokens,
            "remaining_output_token_budget": budget.remaining_output_token_budget,
        }

    def _accounting(self) -> dict[str, int]:
        return {
            "provider_calls": int(getattr(self.adapter, "provider_calls", getattr(self.adapter, "calls", 0))),
            "fake_provider_calls": int(getattr(self.adapter, "fake_provider_calls", 0)),
            "live_api_calls": int(getattr(self.adapter, "live_api_calls", 0)),
            "network_calls": int(getattr(self.adapter, "network_calls", 0)),
        }

    def _finish(self, episode_id: str, replicate_id: int, reason: str, budget: BudgetEnforcer) -> TrajectoryResult:
        if reason not in _TERMINAL:
            raise ValueError(f"unknown termination reason: {reason}")
        self.recorder.append({"event_type": "termination", "termination_reason": reason, "budget_state": self._budget_state(budget), "accounting": self._accounting()})
        accounting = self._accounting()
        return TrajectoryResult(episode_id, replicate_id, reason, tuple(self.recorder.snapshot()), accounting["provider_calls"], accounting["fake_provider_calls"], accounting["live_api_calls"], accounting["network_calls"])

    def _budget_failure(self, budget: BudgetEnforcer) -> str:
        if budget.events and budget.events[-1].get("event") == "timeout_exhausted":
            return "timeout_exhausted"
        if budget.remaining_output_token_budget <= 0:
            return "output_token_budget_exhausted"
        if budget.executed_steps >= budget.config.max_steps:
            return "step_budget_exhausted"
        return "incomplete_episode"

    def _provider_error_type(self, error: BaseException) -> str:
        return str(getattr(error, "error_type", type(error).__name__))

    def run(self, *, episode_id: str, replicate_id: int, agent_visible_context: Any, instructions: str | None = None, evaluator_private_metadata: Mapping[str, Any] | None = None, execution_protocol: str | None = None) -> TrajectoryResult:
        budget = BudgetEnforcer(self.budget_config, clock=self.clock)
        input_value = deepcopy(agent_visible_context)
        prompt = instructions if instructions is not None else self.request_builder.system_prompt
        stateless_replay = bool(getattr(self.request_builder, "stateless_replay", False))
        replay_history = self.request_builder.initial_history(agent_visible_context) if stateless_replay else None
        self.recorder.append({"event_type": "episode_start", "episode_id": episode_id, "replicate_id": replicate_id, "agent_visible_context_hash": _hash(agent_visible_context), "evaluator_private_metadata": deepcopy(dict(evaluator_private_metadata or {})), "execution_protocol": execution_protocol})
        previous_response_id: str | None = None
        provider_attempt_index = 0
        turn_index = 0

        while True:
            if budget.check_timeout():
                return self._finish(episode_id, replicate_id, "timeout_exhausted", budget)
            if not budget.admit_step():
                return self._finish(episode_id, replicate_id, self._budget_failure(budget), budget)
            remaining = budget.max_output_tokens_for_next_response()
            if remaining is None:
                return self._finish(episode_id, replicate_id, self._budget_failure(budget), budget)

            if stateless_replay:
                if replay_history is None:
                    raise RuntimeError("stateless replay history was not initialized")
                request = self.request_builder.build(agent_visible_context=replay_history, replicate_id=replicate_id, remaining_output_token_budget=remaining, instructions=prompt) if turn_index == 0 else self.request_builder.build_replay(history=replay_history, replicate_id=replicate_id, remaining_output_token_budget=remaining, instructions=prompt)
                request_kind = "initial" if turn_index == 0 else "replay"
            elif previous_response_id is None:
                request = self.request_builder.build(agent_visible_context=input_value, replicate_id=replicate_id, remaining_output_token_budget=remaining, instructions=prompt)
                request_kind = "initial"
            else:
                request = self.request_builder.build_continuation(previous_response_id=previous_response_id, function_outputs=input_value, replicate_id=replicate_id, remaining_output_token_budget=remaining, instructions=prompt)
                request_kind = "continuation"
            turn_index += 1
            request_time = _now()
            request_hash = _hash(request)
            self.recorder.append({"event_type": "request", "request_kind": request_kind, "step_index": budget.executed_steps, "previous_response_id": previous_response_id, "request_metadata_hash": _hash(request.get("metadata", {})), "request_hash": request_hash, "max_output_tokens": request["max_output_tokens"], "budget_state": self._budget_state(budget)})

            response: ProviderResponse | None = None
            for retry_index in range(self.retry_policy.max_retries + 1):
                provider_attempt_index += 1
                attempt_time = _now()
                self.recorder.append({"event_type": "provider_attempt", "provider_attempt_index": provider_attempt_index, "retry_index": retry_index, "step_index": budget.executed_steps, "local_request_attempt_time_utc": attempt_time, "request_hash": request_hash})
                try:
                    response = ProviderResponse.from_raw(self.adapter.create_response(request))
                    break
                except BaseException as error:
                    error_type = self._provider_error_type(error)
                    backoff = self.retry_policy.backoff_seconds(retry_index) if self.retry_policy.allows(error, retry_index) else 0.0
                    self.recorder.append({"event_type": "provider_error", "provider_attempt_index": provider_attempt_index, "retry_index": retry_index, "step_index": budget.executed_steps, "error_type": error_type, "backoff_seconds": backoff})
                    if not self.retry_policy.allows(error, retry_index):
                        return self._finish(episode_id, replicate_id, "provider_error", budget)
                    if budget.check_timeout():
                        return self._finish(episode_id, replicate_id, "timeout_exhausted", budget)
                    self.recorder.append({"event_type": "retry", "provider_attempt_index": provider_attempt_index, "retry_index": retry_index + 1, "backoff_seconds": backoff})
                    self.sleep(backoff)
                    if budget.check_timeout():
                        return self._finish(episode_id, replicate_id, "timeout_exhausted", budget)

            if response is None:
                return self._finish(episode_id, replicate_id, "provider_error", budget)

            response_time = _now()
            deadline_reached = budget.check_timeout()
            usage = {"input_tokens": int(response.usage.get("input_tokens", 0)), "output_tokens": int(response.usage.get("output_tokens", 0)), "total_tokens": int(response.usage.get("total_tokens", response.usage.get("input_tokens", 0) + response.usage.get("output_tokens", 0)))}
            budget.record_usage(**usage)
            self.recorder.append({"event_type": "provider_response", "step_index": budget.executed_steps, "previous_response_id": previous_response_id, "provider_response": {"id": response.id, "model": response.model, "created_at": response.created_at, "local_request_time_utc": request_time, "local_response_time_utc": response_time}, "usage": usage, "usage_details": deepcopy(response.usage_details), "provider_output_items": deepcopy(response.output), "deadline_reached": deadline_reached, "budget_state": self._budget_state(budget), "accounting": self._accounting()})
            if deadline_reached:
                return self._finish(episode_id, replicate_id, "timeout_exhausted", budget)
            calls = response.function_calls()
            if not calls:
                return self._finish(episode_id, replicate_id, "completed" if response.has_text_output() else "incomplete_episode", budget)

            continuation: list[dict[str, Any]] = []
            for call in calls:
                call_event = {"event_type": "function_call", "step_index": budget.executed_steps, "function_call": {"call_id": call.call_id, "name": call.name, "arguments_hash": _hash(call.arguments)}}
                try:
                    if not call.call_id or call.call_id == "None" or not call.name or call.name == "None":
                        raise ValueError("provider function call id and name are required")
                    arguments = json.loads(call.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("function arguments must be an object")
                    arguments = self.request_builder.validate_arguments(call.name, arguments)
                except (TypeError, ValueError, json.JSONDecodeError, ToolSchemaValidationError) as error:
                    call_event["error"] = "invalid_function_arguments"
                    call_event["validation_error"] = "invalid_tool_arguments"
                    call_event["validation_message"] = str(error)
                    self.recorder.append(call_event)
                    return self._finish(episode_id, replicate_id, "invalid_function_arguments", budget)

                def execute_tool(name: str = call.name, args: dict[str, Any] = arguments) -> Any:
                    return self.mediator(name, args)

                try:
                    admission = budget.execute_custom_function_result(execute_tool)
                except BaseException as error:
                    admission = type("ToolDispatchFailure", (), {"allowed": True, "reason": None, "outcome": {"admitted": False, "error": type(error).__name__, "message": str(error)}})()
                if not admission.allowed:
                    call_event["tool_result"] = {"admitted": False, "blocked": True, "reason": admission.reason}
                    self.recorder.append(call_event)
                    return self._finish(episode_id, replicate_id, admission.reason or "tool_rejected", budget)
                outcome = admission.outcome
                rejected = isinstance(outcome, Mapping) and (outcome.get("admitted") is False or outcome.get("decision") in {"BLOCK", "REJECT"} or outcome.get("status") in {"blocked", "rejected"})
                call_event["tool_result"] = {"admitted": not rejected, "blocked": False, "mediator_result": deepcopy(outcome)}
                self.recorder.append(call_event)
                if rejected:
                    return self._finish(episode_id, replicate_id, "tool_rejected", budget)
                continuation.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(outcome if outcome is not None else {"admitted": True}, ensure_ascii=False, sort_keys=True)})

            if stateless_replay:
                replay_history = self.request_builder.extend_history(replay_history, response.output, continuation)
                input_value = replay_history
            else:
                previous_response_id = response.id
                input_value = continuation
