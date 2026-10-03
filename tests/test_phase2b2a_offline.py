from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.live_adapter import FakeResponsesAdapter, NetworkDisabledError, OpenAIResponsesAdapter, ProviderError, ResponsesRequestBuilder
from agentbench.live_adapter.fake_provider import function_response, text_response
from agentbench.live_runner.budget import BudgetConfig
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy
from agentbench.live_runner.trajectory import AppendOnlyTrajectory

ROOT = Path(__file__).resolve().parents[1]


def policy() -> RetryPolicy:
    return RetryPolicy.from_file(ROOT / "agentbench/live_protocol/retry_policy.json")


def make_orchestrator(adapter, mediator=None, *, config=None, clock=None, recorder=None):
    return EpisodeOrchestrator(
        adapter=adapter,
        request_builder=ResponsesRequestBuilder(ROOT),
        mediator=mediator or (lambda name, args: {"admitted": True, "name": name, "args": args}),
        budget_config=config,
        clock=clock,
        retry_policy=policy(),
        recorder=recorder,
    )


def call(call_id: str, name: str = "read_file", arguments: str = '{"path":"x"}'):
    return {"call_id": call_id, "name": name, "arguments": arguments}


def test_text_only_completion_uses_one_offline_adapter_call():
    adapter = FakeResponsesAdapter([text_response("r1")])
    result = make_orchestrator(adapter).run(episode_id="ep1", replicate_id=0, agent_visible_context={"opaque": "context"})
    assert result.termination_reason == "completed"
    assert adapter.calls == 1
    assert result.live_api_calls == 1
    assert result.network_calls == 0
    assert any(event["event_type"] == "provider_response" for event in result.events)


def test_function_call_continuation_preserves_provider_call_id_and_shape():
    adapter = FakeResponsesAdapter([function_response("r1", [call("call_1")]), text_response("r2")])
    result = make_orchestrator(adapter).run(episode_id="ep2", replicate_id=1, agent_visible_context={"opaque": "context"})
    assert result.termination_reason == "completed"
    assert adapter.calls == 2
    assert adapter.requests[1]["input"] == [{"type": "function_call_output", "call_id": "call_1", "output": '{"admitted": true, "args": {"path": "x"}, "name": "read_file"}'}]


def test_multiple_function_calls_all_pass_budget_gate():
    invoked = []
    adapter = FakeResponsesAdapter([function_response("r1", [call("a"), call("b")]), text_response("r2")])
    result = make_orchestrator(adapter, lambda name, args: invoked.append((name, args)) or {"admitted": True}).run(episode_id="ep3", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "completed"
    assert len(invoked) == 2
    assert sum(1 for e in result.events if e["event_type"] == "function_call") == 2


def test_twenty_first_function_call_is_blocked_before_mediator():
    invoked = []
    calls = [call(str(i)) for i in range(21)]
    adapter = FakeResponsesAdapter([function_response("r1", calls)])
    result = make_orchestrator(adapter, lambda name, args: invoked.append(name) or {"admitted": True}).run(episode_id="ep4", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "tool_budget_exhausted"
    assert len(invoked) == 20
    assert adapter.calls == 1
    assert result.events[-1]["termination_reason"] == "tool_budget_exhausted"


def test_step_budget_blocks_thirty_first_model_cycle():
    responses = [function_response(f"r{i}", [call(str(i))]) for i in range(31)]
    adapter = FakeResponsesAdapter(responses)
    result = make_orchestrator(adapter, config=BudgetConfig(max_custom_function_calls=100)).run(episode_id="ep5", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "step_budget_exhausted"
    assert adapter.calls == 30
    assert sum(e["event_type"] == "request" for e in result.events) == 30


def test_output_budget_is_cumulative_and_stops_next_response():
    responses = [
        function_response("r1", [call("a")], output_tokens=6000),
        function_response("r2", [call("b")], output_tokens=6000),
        function_response("r3", [call("c")], output_tokens=4000),
        text_response("r4"),
    ]
    adapter = FakeResponsesAdapter(responses)
    result = make_orchestrator(adapter).run(episode_id="ep6", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "output_token_budget_exhausted"
    assert adapter.calls == 3
    assert [r["max_output_tokens"] for r in adapter.requests] == [16000, 10000, 4000]


def test_remaining_output_limit_is_used_by_request_builder():
    request = ResponsesRequestBuilder(ROOT).build(agent_visible_context={}, replicate_id=0, remaining_output_token_budget=2500)
    assert request["max_output_tokens"] == 2500
    assert "seed" not in request and "max_tool_calls" not in request


def test_timeout_prevents_model_and_tool_calls():
    class Clock:
        values = iter((0.0, 900.0))
        def __call__(self):
            return next(self.values, 900.0)
    adapter = FakeResponsesAdapter([text_response("never")])
    result = make_orchestrator(adapter, clock=Clock()).run(episode_id="ep7", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "timeout_exhausted"
    assert adapter.calls == 0


def test_provider_error_retries_without_resetting_budget_or_replaying_tools():
    error = ProviderError("temporary", error_type="TransientProviderError", retryable=True)
    adapter = FakeResponsesAdapter([text_response("r2")], errors=[error])
    result = make_orchestrator(adapter).run(episode_id="ep8", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "completed"
    assert adapter.calls == 2
    assert [e["event_type"] for e in result.events].count("retry") == 1
    responses = [e for e in result.events if e["event_type"] == "provider_response"]
    assert responses[0]["budget_state"]["executed_steps"] == 1


def test_malformed_arguments_are_explicit_and_do_not_crash():
    adapter = FakeResponsesAdapter([function_response("r1", [call("bad", arguments="not-json")])])
    result = make_orchestrator(adapter).run(episode_id="ep9", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "invalid_function_arguments"
    assert any(e.get("error") == "invalid_function_arguments" for e in result.events)


def test_mediator_rejection_is_recorded():
    adapter = FakeResponsesAdapter([function_response("r1", [call("reject")])])
    result = make_orchestrator(adapter, lambda name, args: {"decision": "BLOCK", "message": "rejected"}).run(episode_id="ep10", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "tool_rejected"
    event = next(e for e in result.events if e["event_type"] == "function_call")
    assert event["tool_result"]["admitted"] is False


def test_empty_provider_output_has_incomplete_termination():
    adapter = FakeResponsesAdapter([{"id": "r1", "model": "gpt-5.6-sol", "created_at": "t", "output": [], "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}])
    result = make_orchestrator(adapter).run(episode_id="ep11", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "incomplete_episode"


def test_condition_private_metadata_never_enters_agent_input():
    for private_label in ("A0", "A1", "A2", "A3", "A4"):
        adapter = FakeResponsesAdapter([text_response("r1")])
        result = make_orchestrator(adapter).run(episode_id=f"{private_label}-ep", replicate_id=0, agent_visible_context={"opaque": "same"}, evaluator_private_metadata={"condition": private_label})
        assert result.termination_reason == "completed"
        visible = json.dumps(adapter.requests[0]["input"] + adapter.requests[0]["instructions"], ensure_ascii=False) if isinstance(adapter.requests[0]["input"], list) else json.dumps({"input": adapter.requests[0]["input"], "instructions": adapter.requests[0]["instructions"]}, ensure_ascii=False)
        assert all(token not in visible for token in ("target_rule_id", "target_stage", "family", "condition", "ground_truth", "A0", "A1", "A2", "A3", "A4"))
        assert any(event["event_type"] == "episode_start" and event["evaluator_private_metadata"]["condition"] == private_label for event in result.events)


def test_append_only_trajectory_does_not_alias_input():
    recorder = AppendOnlyTrajectory()
    event = {"event_type": "request", "nested": {"value": 1}}
    recorder.append(event)
    event["nested"]["value"] = 2
    assert recorder.snapshot()[0]["nested"]["value"] == 1


def test_fake_path_has_an_explicit_no_network_guard(monkeypatch):
    import socket

    def forbidden_socket(*args, **kwargs):
        raise AssertionError("offline fake path attempted a socket")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    adapter = FakeResponsesAdapter([text_response("r1")])
    result = make_orchestrator(adapter).run(episode_id="ep12", replicate_id=0, agent_visible_context={"opaque": "context"})
    assert result.termination_reason == "completed"
    assert result.network_calls == 0


def test_openai_adapter_without_injected_transport_is_offline_only():
    with pytest.raises(NetworkDisabledError):
        OpenAIResponsesAdapter().create_response({})
