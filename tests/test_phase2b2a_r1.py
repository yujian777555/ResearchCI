from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.live_adapter import FakeResponsesAdapter, ProviderError, ResponsesRequestBuilder, ToolSchemaValidationError
from agentbench.live_adapter.fake_provider import function_response, text_response
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy

ROOT = Path(__file__).resolve().parents[1]


def builder() -> ResponsesRequestBuilder:
    return ResponsesRequestBuilder(ROOT)


def make(adapter, mediator=None, *, clock=None, sleep=None):
    return EpisodeOrchestrator(adapter=adapter, request_builder=builder(), mediator=mediator or (lambda name, args: {"admitted": True}), retry_policy=RetryPolicy.from_file(ROOT / "agentbench/live_protocol/retry_policy.json"), clock=clock, sleep=sleep)


def tool_call(call_id: str, name: str, payload: dict):
    return {"call_id": call_id, "name": name, "arguments": json.dumps(payload, ensure_ascii=False, sort_keys=True)}


def first_scenario():
    return json.loads(next((ROOT / "agentbench/scenarios").glob("*.json")).read_text(encoding="utf-8"))


def test_continuation_contract_uses_previous_response_id_and_omits_repeated_state():
    contract = json.loads((ROOT / "agentbench/live_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
    assert contract["conversation_state_mode"] == "previous_response_id"
    assert contract["continuation_previous_response_id_field"] == "previous_response_id"
    b = builder()
    request = b.build_continuation(previous_response_id="resp_1", function_outputs=[{"type": "function_call_output", "call_id": "call_1", "output": "{}"}], replicate_id=0, remaining_output_token_budget=2500)
    assert request["previous_response_id"] == "resp_1"
    assert request["input"][0]["call_id"] == "call_1"
    assert request["instructions"] == builder().system_prompt
    assert request["tools"] == builder().tools


def test_multi_call_continuation_preserves_exact_provider_ids():
    payload = {"path": "README.md"}
    adapter = FakeResponsesAdapter([function_response("resp_1", [tool_call("call_1", "read_file", payload), tool_call("call_2", "read_file", payload)]), text_response("resp_2")])
    result = make(adapter).run(episode_id="r1-multi", replicate_id=0, agent_visible_context={"opaque": "x"})
    assert result.termination_reason == "completed"
    assert adapter.requests[1]["previous_response_id"] == "resp_1"
    assert [item["call_id"] for item in adapter.requests[1]["input"]] == ["call_1", "call_2"]
    assert result.provider_calls == 2 and result.fake_provider_calls == 2 and result.live_api_calls == 0 and result.network_calls == 0


def test_all_tool_schemas_accept_representative_domain_payloads():
    b = builder(); state = first_scenario()["initial_state"]
    payloads = {
        "read_file": {"path": "README.md"},
        "write_file": {"path": "candidate_change.py", "content": "x = 1"},
        "inspect_experiment_state": {},
        "run_experiment": state["pre_run"],
        "consume_cache": state["pre_cache_consume"],
        "record_run_result": {"run_result": state["pre_aggregate"]["observed_results"][0]},
        "propose_aggregate": {"aggregate": state["pre_aggregate"]},
        "finish_episode": {"summary": "completed with admitted evidence"},
    }
    for name, payload in payloads.items():
        b.validate_arguments(name, payload)


def test_invalid_payloads_are_rejected_without_coercion():
    b = builder(); state = first_scenario()["initial_state"]
    run = json.loads(json.dumps(state["pre_run"]))
    del run["candidate_intent"]["run_id"]
    with pytest.raises(ToolSchemaValidationError): b.validate_arguments("run_experiment", run)
    run = json.loads(json.dumps(state["pre_run"]))
    run["candidate_intent"]["seed"] = "1"
    with pytest.raises(ToolSchemaValidationError): b.validate_arguments("run_experiment", run)
    run = json.loads(json.dumps(state["pre_run"]))
    run["unknown"] = True
    with pytest.raises(ToolSchemaValidationError): b.validate_arguments("run_experiment", run)
    aggregate = {"aggregate": {"experiment_id": "x", "baseline_run_ids": [], "candidate_run_ids": [], "declared_seed_set": [1], "aggregation_metric": "accuracy", "observed_results": [{"run_id": "x"}]}}
    with pytest.raises(ToolSchemaValidationError): b.validate_arguments("propose_aggregate", aggregate)


@pytest.mark.parametrize("name", ["run_experiment", "consume_cache", "record_run_result", "propose_aggregate"])
def test_complex_tool_payload_reaches_mediator_unchanged(name):
    state = first_scenario()["initial_state"]
    payload = {"run_experiment": state["pre_run"], "consume_cache": state["pre_cache_consume"], "record_run_result": {"run_result": state["pre_aggregate"]["observed_results"][0]}, "propose_aggregate": {"aggregate": state["pre_aggregate"]}}[name]
    seen = []
    adapter = FakeResponsesAdapter([function_response("resp_1", [tool_call("call_1", name, payload)]), text_response("resp_2")])
    result = make(adapter, lambda tool, args: seen.append((tool, args)) or {"admitted": True}).run(episode_id=f"r1-{name}", replicate_id=0, agent_visible_context={"opaque": "x"})
    assert result.termination_reason == "completed"
    assert seen == [(name, payload)]



def test_retry_backoff_sequence_is_bounded_and_budgets_are_not_reset():
    errors = [ProviderError("t1", error_type="TransientProviderError", retryable=True), ProviderError("t2", error_type="TransientProviderError", retryable=True)]
    sleeps = []
    adapter = FakeResponsesAdapter([*errors, text_response("resp_3")])
    result = make(adapter, sleep=sleeps.append).run(episode_id="r1-retry", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "completed"
    assert sleeps == [1.0, 2.0]
    assert result.provider_calls == 3 and result.fake_provider_calls == 3
    assert [e["retry_index"] for e in result.events if e["event_type"] == "retry"] == [1, 2]
    assert [e["backoff_seconds"] for e in result.events if e["event_type"] == "retry"] == [1.0, 2.0]
    assert [e["budget_state"]["executed_steps"] for e in result.events if e["event_type"] == "provider_response"] == [1]


class Clock:
    def __init__(self, value=0.0): self.value = value
    def __call__(self): return self.value


def test_timeout_is_rechecked_during_retry_backoff_before_next_provider_call():
    clock = Clock(0.0)
    sleeps = []
    def sleep(seconds): sleeps.append(seconds); clock.value = 900.0
    adapter = FakeResponsesAdapter([ProviderError("temporary", error_type="TransientProviderError", retryable=True), text_response("never")])
    result = make(adapter, clock=clock, sleep=sleep).run(episode_id="r1-timeout", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "timeout_exhausted"
    assert adapter.provider_calls == 1
    assert sleeps == [1.0]


def test_successful_tool_is_not_replayed_after_later_provider_retry():
    seen = []
    adapter = FakeResponsesAdapter([function_response("resp_1", [tool_call("call_1", "read_file", {"path": "README.md"})]), ProviderError("temporary", error_type="TransientProviderError", retryable=True), text_response("resp_2")])
    result = make(adapter, lambda name, args: seen.append((name, args)) or {"admitted": True}, sleep=lambda _seconds: None).run(episode_id="r1-no-replay", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "completed"
    assert seen == [("read_file", {"path": "README.md"})]
    assert adapter.provider_calls == 3 and result.fake_provider_calls == 3 and result.live_api_calls == 0


def test_agent_visible_continuation_projection_has_no_private_metadata():
    adapter = FakeResponsesAdapter([function_response("resp_1", [tool_call("call_1", "read_file", {"path": "README.md"})]), text_response("resp_2")])
    make(adapter, sleep=lambda _seconds: None).run(episode_id="r1-leak", replicate_id=0, agent_visible_context={"opaque": "x"}, evaluator_private_metadata={"condition": "A0"})
    visible = json.dumps(adapter.requests[0]["input"], ensure_ascii=False) + json.dumps(adapter.requests[1]["input"], ensure_ascii=False)
    assert all(token not in visible for token in ("condition", "A0", "A1", "A2", "A3", "A4", "family", "ground_truth", "target_rule_id", "target_stage"))
