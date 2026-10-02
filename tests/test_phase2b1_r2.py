from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentbench.live_runner.budget import BudgetConfig, BudgetEnforcer
from agentbench.live_runner.dry_run import dry_run
from agentbench.live_runner.freeze import composite_protocol_hash, request_preview

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def test_runtime_config_uses_runner_side_canonical_budget_fields():
    import yaml

    config = yaml.safe_load((ROOT / "agentbench/live_protocol/agent_config.yaml").read_text(encoding="utf-8"))
    runtime = config["runtime"]
    assert runtime == {"max_steps": 30, "max_custom_function_calls": 20, "timeout_seconds": 900, "cumulative_output_token_budget": 16000}
    assert "max_tool_calls" not in runtime
    assert "token_budget" not in runtime


def test_twenty_custom_calls_execute_and_twenty_first_is_blocked_before_executor():
    enforcer = BudgetEnforcer()
    executed = []
    for index in range(20):
        allowed, _ = enforcer.execute_custom_function(lambda index=index: executed.append(index))
        assert allowed is True
    allowed, _ = enforcer.execute_custom_function(lambda: executed.append("blocked"))
    assert allowed is False
    assert "blocked" not in executed
    assert enforcer.executed_custom_function_calls == 20
    assert enforcer.events[-1] == {"event": "tool_budget_exhausted", "executed_custom_function_calls": 20, "attempted_call_index": 21}


def test_thirtieth_step_runs_and_thirty_first_is_explicitly_blocked():
    enforcer = BudgetEnforcer()
    assert [enforcer.admit_step() for _ in range(30)] == [True] * 30
    assert enforcer.admit_step() is False
    assert enforcer.events[-1]["event"] == "step_budget_exhausted"
    assert enforcer.events[-1]["attempted_step_index"] == 31


def test_cumulative_output_budget_caps_each_response_and_stops_at_zero():
    enforcer = BudgetEnforcer(BudgetConfig(provider_per_response_output_limit=8000))
    assert enforcer.max_output_tokens_for_next_response() == 8000
    enforcer.record_usage(input_tokens=100, output_tokens=6000, total_tokens=6100)
    assert enforcer.max_output_tokens_for_next_response() == 8000
    enforcer.record_usage(input_tokens=100, output_tokens=6000, total_tokens=6100)
    assert enforcer.max_output_tokens_for_next_response() == 4000
    enforcer.record_usage(input_tokens=100, output_tokens=4000, total_tokens=4100)
    assert enforcer.max_output_tokens_for_next_response() is None
    assert enforcer.events[-1]["event"] == "output_token_budget_exhausted"


def test_remaining_budget_limits_next_request():
    enforcer = BudgetEnforcer(BudgetConfig(provider_per_response_output_limit=128000))
    enforcer.record_usage(input_tokens=0, output_tokens=13500)
    assert enforcer.max_output_tokens_for_next_response() == 2500


def test_timeout_uses_injected_monotonic_clock_and_stops_next_action():
    clock = FakeClock()
    enforcer = BudgetEnforcer(BudgetConfig(timeout_seconds=900), clock=clock)
    assert enforcer.admit_step() is True
    clock.value = 900
    assert enforcer.admit_step() is False
    assert enforcer.events[-1]["event"] == "timeout_exhausted"


def test_budget_enforcement_is_independent_of_condition_labels():
    snapshots = []
    for _label in ("A0", "A1", "A2", "A3", "A4"):
        enforcer = BudgetEnforcer()
        for _ in range(20):
            enforcer.execute_custom_function(lambda: None)
        enforcer.execute_custom_function(lambda: None)
        snapshots.append((enforcer.executed_custom_function_calls, enforcer.events))
    assert all(snapshot == snapshots[0] for snapshot in snapshots)


def test_provider_request_has_no_provider_max_tool_calls_or_seed():
    preview = request_preview(ROOT, 0)["request"]
    assert "max_tool_calls" not in preview
    assert "seed" not in preview
    assert preview["max_output_tokens"] == 16000


def test_composite_hash_changes_when_budget_semantics_change(tmp_path):
    copied = tmp_path / "repo"
    shutil.copytree(ROOT / "agentbench", copied / "agentbench")
    before = composite_protocol_hash(copied)
    config = copied / "agentbench/live_protocol/agent_config.yaml"
    config.write_text(config.read_text(encoding="utf-8").replace("max_steps: 30", "max_steps: 29"), encoding="utf-8")
    assert composite_protocol_hash(copied) != before


def test_dry_run_does_not_create_episode_or_network_activity():
    assert dry_run().as_dict() == {"live_call": False, "network_calls": 0, "executed_steps": 0, "executed_tool_calls": 0, "result_count": 0}
