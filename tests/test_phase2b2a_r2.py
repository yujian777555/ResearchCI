from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentbench.live_adapter import FakeResponsesAdapter, ResponsesRequestBuilder, strict_schema_issues, validate_provider_tool_schemas
from agentbench.live_adapter.fake_provider import function_response, text_response
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy

ROOT = Path(__file__).resolve().parents[1]


def b(): return ResponsesRequestBuilder(ROOT)

def call(call_id, name, payload):
    return {"call_id": call_id, "name": name, "arguments": json.dumps(payload, ensure_ascii=False, sort_keys=True)}

def make(adapter, mediator, *, clock=None, sleep=None):
    return EpisodeOrchestrator(adapter=adapter, request_builder=b(), mediator=mediator, retry_policy=RetryPolicy.from_file(ROOT / "agentbench/live_protocol/retry_policy.json"), clock=clock, sleep=sleep)


def test_every_emitted_tool_is_provider_strict_recursively():
    tools = b().tools
    validate_provider_tool_schemas([{"type": tool["name"], "parameters": tool["parameters"]} for tool in tools])
    for tool in tools:
        assert tool["strict"] is True
        assert strict_schema_issues(tool["parameters"]) == []


def test_optional_domain_fields_use_nullable_required_provider_representation():
    builder = b()
    action = next(item for item in builder.tool_schema["actions"] if item["type"] == "run_experiment")
    schema = action["parameters"]
    assert set(schema["properties"]) == set(schema["required"])
    assert schema["properties"]["baseline_intents"]["type"] == ["array", "null"]
    assert schema["properties"]["candidate_intents"]["type"] == ["array", "null"]
    scenario = json.loads(next((ROOT / "agentbench/scenarios").glob("*.json")).read_text(encoding="utf-8"))["initial_state"]["pre_run"]
    assert builder.validate_arguments("run_experiment", scenario) == scenario


def test_initial_and_continuation_have_identical_frozen_generation_config():
    builder = b()
    initial = builder.build(agent_visible_context={"opaque": "initial"}, replicate_id=0, remaining_output_token_budget=16000)
    continuation = builder.build_continuation(previous_response_id="resp_1", function_outputs=[{"type": "function_call_output", "call_id": "call_1", "output": "{}"}], replicate_id=0, remaining_output_token_budget=15000)
    parity_fields = ("model", "instructions", "temperature", "top_p", "reasoning", "store", "parallel_tool_calls", "tools")
    assert all(initial[field] == continuation[field] for field in parity_fields)
    assert initial["reasoning"] == {"effort": "medium", "context": "all_turns"}
    assert initial["store"] is True and initial["parallel_tool_calls"] is True
    assert initial["max_output_tokens"] == 16000 and continuation["max_output_tokens"] == 15000
    assert "previous_response_id" not in initial and continuation["previous_response_id"] == "resp_1"


@pytest.mark.parametrize("profile", ["tabular_sklearn", "vision_pytorch", "text_classification"])
def test_three_profiles_real_payloads_are_schema_compatible_and_reach_mediator(profile):
    path = next((ROOT / "agentbench/scenarios").glob(f"*_{profile}.json"))
    state = json.loads(path.read_text(encoding="utf-8"))["initial_state"]
    payload = state["pre_run"]
    seen = []
    adapter = FakeResponsesAdapter([function_response("resp_1", [call("call_1", "run_experiment", payload)]), text_response("resp_2")])
    result = make(adapter, lambda name, args: seen.append((name, args)) or {"admitted": True}, sleep=lambda _seconds: None).run(episode_id=f"r2-{profile}", replicate_id=0, agent_visible_context={"opaque": "profile"})
    assert result.termination_reason == "completed"
    assert seen == [("run_experiment", payload)]


class Clock:
    value = 0.0
    def __call__(self): return self.value


def test_provider_latency_after_deadline_prevents_all_tool_dispatch():
    clock = Clock()
    class LatencyAdapter:
        adapter_kind = "fake"; provider_calls = 0; fake_provider_calls = 0; live_api_calls = 0; network_calls = 0
        def create_response(self, request):
            self.provider_calls += 1; self.fake_provider_calls += 1; clock.value = 900.0
            return function_response("resp_1", [call("call_1", "read_file", {"path": "README.md"})])
    seen=[]
    result = make(LatencyAdapter(), lambda name,args: seen.append((name,args)) or {"admitted":True}, clock=clock, sleep=lambda _seconds: None).run(episode_id="r2-latency", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "timeout_exhausted"
    assert seen == []


def test_timeout_between_multiple_tool_calls_blocks_remaining_calls():
    clock = Clock(); seen=[]
    def mediator(name, args):
        seen.append((name,args)); clock.value = 900.0; return {"admitted":True}
    adapter = FakeResponsesAdapter([function_response("resp_1", [call("call_1", "read_file", {"path":"a"}), call("call_2", "read_file", {"path":"b"})])])
    result = make(adapter, mediator, clock=clock, sleep=lambda _seconds: None).run(episode_id="r2-between", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "timeout_exhausted"
    assert [name for name,_ in seen] == ["read_file"]


def test_true_twenty_first_tool_call_stays_tool_budget_exhausted():
    seen=[]
    adapter = FakeResponsesAdapter([function_response("resp_1", [call(str(i), "read_file", {"path":"x"}) for i in range(21)])])
    result = make(adapter, lambda name,args: seen.append(name) or {"admitted":True}, sleep=lambda _seconds: None).run(episode_id="r2-tool-budget", replicate_id=0, agent_visible_context={})
    assert result.termination_reason == "tool_budget_exhausted"
    assert len(seen) == 20
    assert result.live_api_calls == 0 and result.network_calls == 0


def test_frozen_generation_config_is_explicit_in_agent_and_provider_contract():
    config = yaml.safe_load((ROOT / "agentbench/live_protocol/agent_config.yaml").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "agentbench/live_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
    assert config["reasoning"] == {"effort":"medium", "context":"all_turns"}
    assert config["provider_state"] == {"store":True, "continuation_mode":"previous_response_id"}
    assert config["tool_execution"] == {"parallel_tool_calls":True}
    assert contract["generation_config"] == {"reasoning":{"effort":"medium","context":"all_turns"},"store":True,"parallel_tool_calls":True}
