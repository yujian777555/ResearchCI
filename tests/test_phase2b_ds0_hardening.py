from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentbench.deepseek_adapter import DeepSeekRequestBuilder, FakeDeepSeekResponsesAdapter
from agentbench.deepseek_adapter.deepseek_responses import DeepSeekResponsesAdapter
from agentbench.live_adapter.errors import ProviderError
from agentbench.live_runner.budget import BudgetConfig
from agentbench.live_runner.orchestrator import EpisodeOrchestrator

ROOT = Path(__file__).resolve().parents[1]


def call(index, name="read_file", payload=None):
    return {"type": "function_call", "call_id": f"call_{index}", "name": name,
            "arguments": json.dumps(payload if payload is not None else {"path": "local.txt"})}


def raw(index, output, tokens=1):
    return {"id": f"response_{index}", "model": "deepseek-v4-pro", "created_at": 1791072000,
            "output": output, "usage": {"input_tokens": 2, "output_tokens": tokens,
                                       "total_tokens": tokens + 2}}


def run(adapter, mediator=None, **kwargs):
    return EpisodeOrchestrator(adapter=adapter, request_builder=DeepSeekRequestBuilder(ROOT),
                               mediator=mediator or (lambda name, args: {"admitted": True}),
                               sleep=kwargs.pop("sleep", lambda _: None), **kwargs).run(
        episode_id="ds-offline-unit", replicate_id=0, agent_visible_context="original task",
        evaluator_private_metadata={"condition": "A4", "target_rule_id": "private"})


def message(text="done"):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def test_mapping_response_preserves_reasoning_content_and_usage_details():
    item = {"type": "reasoning", "id": "rs_exact", "status": "completed", "summary": [],
            "content": [{"type": "reasoning_text", "text": "synthetic context"}]}
    value = raw(1, [item, call(1)])
    value["usage"].update(input_tokens_details={"cached_tokens": 1},
                          output_tokens_details={"reasoning_tokens": 1})
    parsed = DeepSeekResponsesAdapter.parse_response(value)
    assert parsed.output == tuple(value["output"])
    assert parsed.usage_details == {"input_tokens_details": {"cached_tokens": 1},
                                    "output_tokens_details": {"reasoning_tokens": 1}}
    value["output"][0]["content"][0]["text"] = "mutated"
    assert parsed.output[0]["content"][0]["text"] == "synthetic context"


def test_sdk_response_parser_keeps_every_output_field_without_string_coercion():
    class SDKItem:
        def __init__(self, value): self.value = value
        def model_dump(self, **kwargs): return deepcopy(self.value)
    items = [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "trace"}],
              "id": "rs_1", "status": "completed", "summary": []}, call(1), message()]
    sdk = SimpleNamespace(id="sdk-response", model="deepseek-v4-pro", created_at=42,
                          output=[SDKItem(item) for item in items],
                          usage=SimpleNamespace(input_tokens=3, output_tokens=5, total_tokens=8,
                                                input_tokens_details=SimpleNamespace(cached_tokens=2),
                                                output_tokens_details=SimpleNamespace(reasoning_tokens=4)))
    result = DeepSeekResponsesAdapter.parse_response(sdk)
    assert result.output == tuple(items)
    assert result.usage == {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
    assert result.usage_details["input_tokens_details"]["cached_tokens"] == 2


def test_three_turn_history_exactness_order_and_no_tool_reexecution():
    first = [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "r1"}]},
             call(1), message("intermediate")]
    second = [call(2), {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "r2"}]}]
    adapter = FakeDeepSeekResponsesAdapter([raw(1, first), raw(2, second), raw(3, [message()])])
    seen = []
    result = run(adapter, lambda name, args: seen.append((name, args)) or {"admitted": True})
    assert result.termination_reason == "completed"
    assert len(seen) == 2
    initial = adapter.requests[0]["input"]
    assert adapter.requests[1]["input"][:len(initial)] == initial
    assert adapter.requests[2]["input"][:len(initial)] == initial
    assert adapter.requests[1]["input"][len(initial):len(initial)+len(first)] == first
    assert adapter.requests[2]["input"][:len(adapter.requests[1]["input"])] == adapter.requests[1]["input"]
    tail = adapter.requests[2]["input"][len(adapter.requests[1]["input"]):]
    assert tail[:len(second)] == second
    assert tail[-1]["call_id"] == "call_2"
    visible = json.dumps(adapter.requests)
    for token in ("condition", "A0", "A1", "A2", "A3", "A4", "target_rule_id", "target_stage", "ground_truth", "family"):
        assert token not in visible


@pytest.mark.parametrize("field", ["previous_response_id", "store", "metadata", "conversation", "temperature", "seed", "parallel_tool_calls", "reasoning_context", "arbitrary"])
def test_request_validation_rejects_unfrozen_field_injection(field):
    builder = DeepSeekRequestBuilder(ROOT)
    request = builder.build(agent_visible_context=builder.initial_history("task"), replicate_id=0,
                            remaining_output_token_budget=2500)
    request[field] = True
    with pytest.raises(ValueError): builder.validate_request(request)


def test_step_31_is_blocked_on_deepseek_path():
    adapter = FakeDeepSeekResponsesAdapter([raw(i, [call(i)]) for i in range(31)])
    result = run(adapter, budget_config=BudgetConfig(max_custom_function_calls=100))
    assert result.termination_reason == "step_budget_exhausted"
    assert result.provider_calls == 30


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


def test_deepseek_provider_latency_timeout_blocks_mediator():
    clock = Clock()
    class SlowFake(FakeDeepSeekResponsesAdapter):
        def create_response(self, request):
            clock.value = 900
            return super().create_response(request)
    seen = []
    adapter = SlowFake([raw(1, [call(1)])])
    result = run(adapter, lambda name, args: seen.append(args), clock=clock)
    assert result.termination_reason == "timeout_exhausted"
    assert seen == []


def test_deepseek_timeout_between_calls_is_not_tool_exhaustion():
    clock = Clock()
    seen = []
    def mediator(name, args):
        seen.append(args)
        clock.value = 900
        return {"admitted": True}
    result = run(FakeDeepSeekResponsesAdapter([raw(1, [call(1), call(2)])]), mediator, clock=clock)
    assert result.termination_reason == "timeout_exhausted"
    assert len(seen) == 1


def test_retry_keeps_history_tokens_steps_and_successful_tool_execution():
    error = ProviderError("synthetic transient", error_type="RateLimitError", retryable=True)
    adapter = FakeDeepSeekResponsesAdapter([raw(1, [call(1)], tokens=6000), error, raw(2, [message()])])
    seen, delays = [], []
    result = run(adapter, lambda name, args: seen.append(args) or {"admitted": True}, sleep=delays.append)
    assert result.termination_reason == "completed"
    assert len(seen) == 1
    assert delays == [1.0]
    assert adapter.requests[1] == adapter.requests[2]
    assert adapter.requests[2]["max_output_tokens"] == 10000
    assert result.events[-1]["budget_state"]["executed_steps"] == 2
    assert result.provider_calls == result.fake_provider_calls == 3
    assert result.live_api_calls == result.network_calls == 0


def test_retry_timeout_never_starts_another_provider_attempt():
    clock = Clock()
    adapter = FakeDeepSeekResponsesAdapter([ProviderError("test", error_type="RateLimitError", retryable=True),
                                           raw(1, [message()])])
    def sleep(delay): clock.value = 900
    result = run(adapter, clock=clock, sleep=sleep)
    assert result.termination_reason == "timeout_exhausted"
    assert result.provider_calls == 1


@pytest.mark.parametrize("name,args", [
    ("read_file", '{"path":3}'), ("read_file", '{}'), ("unknown", '{}'),
    ("read_file", '{"path":"x","extra":true}'), ("read_file", 'not JSON'),
    ("run_experiment", '{"baseline_intent":{}}')])
def test_invalid_arguments_never_enter_mediator(name, args):
    item = call(1)
    item.update(name=name, arguments=args)
    seen = []
    result = run(FakeDeepSeekResponsesAdapter([raw(1, [item])]), lambda name, args: seen.append(args))
    assert result.termination_reason == "invalid_function_arguments"
    assert seen == []


@pytest.mark.parametrize("profile", ["tabular_sklearn", "vision_pytorch", "text_classification"])
@pytest.mark.parametrize("tool", ["run_experiment", "consume_cache", "record_run_result", "propose_aggregate"])
def test_representative_profile_arguments_reach_mediator_unchanged(profile, tool):
    state = json.loads(next((ROOT / "agentbench/scenarios").glob(f"*_{profile}.json")).read_text())["initial_state"]
    args = {"run_experiment": state["pre_run"], "consume_cache": state["pre_cache_consume"],
            "record_run_result": {"run_result": state["pre_aggregate"]["observed_results"][0]},
            "propose_aggregate": {"aggregate": state["pre_aggregate"]}}[tool]
    seen = []
    adapter = FakeDeepSeekResponsesAdapter([raw(1, [call(1, tool, args)]), raw(2, [message()])])
    result = run(adapter, lambda name, payload: seen.append((name, payload)) or {"admitted": True})
    assert result.termination_reason == "completed"
    assert seen == [(tool, args)]
