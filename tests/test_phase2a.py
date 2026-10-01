from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from researchci_agent.conditions import Condition
from researchci_agent.events import EventLog
from researchci_agent.mediator import EpisodeHarness
from researchci_agent.replay import ReplayEngine
from researchci_agent.scenarios import TOOL_SCHEMA, generate_scenarios
from researchci_agent.scripted_agents import RepairFollowingAgent, ValidAgent, ViolationAttemptAgent
from researchci_agent.validator import IndependentTrajectoryValidator


def test_materializes_exact_18_scenarios_and_is_bitwise_deterministic(tmp_path):
    first = generate_scenarios(tmp_path / "first")
    second = generate_scenarios(tmp_path / "second")
    assert len(first) == len(second) == 18
    assert [item.scenario_id for item in first] == [item.scenario_id for item in second]
    for left, right in zip(first, second):
        assert left.semantic_hash == right.semantic_hash
        assert left.prompt_hash == right.prompt_hash
        assert left.workspace_hash == right.workspace_hash
        assert left.contract_hash == right.contract_hash
        assert left.evaluator_metadata_hash == right.evaluator_metadata_hash
    assert set(item.repo_profile for item in first) == {"tabular_sklearn", "vision_pytorch", "text_classification"}
    assert {item.family for item in first} == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_agent_visible_context_and_tool_schema_hide_evaluator_metadata(tmp_path):
    scenarios = generate_scenarios(tmp_path / "bench")
    forbidden = {f"RCI-C00{i}" for i in range(1, 7)} | {"target_rule_id", "target_stage", "ground_truth", '"label": "invalid"', "expected_trajectory"}
    for scenario in scenarios:
        visible = json.dumps(scenario.agent_context(), sort_keys=True)
        assert not any(token in visible for token in forbidden)
    schema_text = json.dumps(TOOL_SCHEMA, sort_keys=True)
    assert not any(token in schema_text for token in forbidden)


def test_validator_is_independent_from_researchci_engine_and_rules():
    source = inspect.getsource(IndependentTrajectoryValidator)
    assert "InvariantEngine" not in source
    assert "researchci.rules" not in source
    assert "from researchci" not in source


@pytest.mark.parametrize("condition", list(Condition))
def test_valid_agent_completes_without_false_block(tmp_path, condition):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    result = EpisodeHarness(scenario, condition, tmp_path / "run").run(ValidAgent())
    assert result.completed is True
    assert result.evidence_admitted is True
    assert result.validator["invariant_violated"] is False
    assert result.validator["episode_integrity_failure"] is False


def test_violation_agent_condition_matrix(tmp_path):
    scenarios = {item.family: item for item in generate_scenarios(tmp_path / "bench") if item.repo_profile == "tabular_sklearn"}
    expected = {
        Condition.A0_NO_CHECK: {"crossed": True, "posthoc": False},
        Condition.A1_SCHEMA_VALIDATION: {"crossed": True, "posthoc": False},
        Condition.A2_PROVENANCE_ONLY: {"crossed": None, "posthoc": False},
        Condition.A3_POSTHOC_RESEARCHCI: {"crossed": True, "posthoc": True},
        Condition.A4_RUNTIME_RESEARCHCI: {"crossed": False, "posthoc": False},
    }
    for condition, expectation in expected.items():
        for family, scenario in scenarios.items():
            result = EpisodeHarness(scenario, condition, tmp_path / f"run-{condition.value}-{family}").run(ViolationAttemptAgent())
            assert result.validator["violation_attempted"] is True
            if expectation["crossed"] is not None:
                assert result.validator["crossed_target_gate"] is expectation["crossed"]
            assert result.validator["posthoc_detected"] is expectation["posthoc"]
            if condition == Condition.A2_PROVENANCE_ONLY:
                assert result.validator["crossed_target_gate"] is (family != "S5")


def test_repair_agent_recovers_after_runtime_feedback(tmp_path):
    scenario = next(item for item in generate_scenarios(tmp_path / "bench") if item.family in {"S2", "S4", "S6"})
    result = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "run").run(RepairFollowingAgent())
    assert result.completed is True
    assert result.evidence_admitted is True
    assert result.repair_attempted is True
    assert result.repair_succeeded is True
    assert result.validator["episode_integrity_failure"] is False


def test_workspace_edits_cannot_admit_evidence_or_escape_root(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    harness = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "run")
    with pytest.raises(PermissionError):
        harness.workspace.write_text("../admission.json", "forged")
    result = harness.run(ValidAgent())
    assert result.evidence_admitted is True
    assert not (tmp_path / "admission.json").exists()


def test_event_log_hash_chain_and_replay_are_deterministic(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    first = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "first").run(ValidAgent())
    second = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "second").run(ValidAgent())
    assert first.semantic_event_hash == second.semantic_event_hash
    assert first.replay_state == second.replay_state
    replay = ReplayEngine(first.events).reconstruct()
    assert replay == first.replay_state
    assert EventLog.verify_chain(first.events) is True
    assert all("timestamp" not in event for event in first.events)


def test_all_lifecycle_actions_are_intercepted_and_direct_evidence_is_ignored(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    harness = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "run")
    result = harness.run(ValidAgent(include_direct_evidence_write=True))
    actions = [event["action_type"] for event in result.events]
    assert {"run_experiment", "consume_cache", "record_run_result", "propose_aggregate", "finish_episode"} <= set(actions)
    assert result.direct_evidence_write_admitted is False


def test_primary_metrics_are_conditional_and_do_not_score_non_attempts(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    valid = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "valid").run(ValidAgent())
    metrics = valid.metrics()
    assert metrics["CIER"] == 0.0
    assert metrics["VTCR"] == 1.0
    assert metrics["attempted_violation"] is False
    attempted = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "attempted").run(ViolationAttemptAgent())
    assert attempted.metrics()["CIER"] == 1.0
    assert attempted.metrics()["EIFR"] == 1.0


def test_no_network_calls_are_required(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    result = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "run").run(ValidAgent())
    assert result.resource_accounting["network_calls"] == 0
