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
from researchci_agent.schema import AgentAction, AgentObservation


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


class _SpyAgent:
    def __init__(self, action=None):
        self.context = None
        self.action = action or AgentAction("finish_episode", {"summary": "spy"})

    def start_episode(self, context):
        self.context = context

    def next_action(self, observation):
        return self.action


def test_actual_agent_context_is_opaque_and_condition_blind(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    contexts = []
    for index, condition in enumerate(Condition):
        spy = _SpyAgent()
        EpisodeHarness(scenario, condition, tmp_path / f"context-{index}").run(spy)
        contexts.append(spy.context)
    forbidden = {"hidden_metadata", "family", "target_rule_id", "target_stage", "_scenario", "A0", "A1", "A2", "A3", "A4", "S1", "S2", "S3", "S4", "S5", "S6"}
    for context in contexts:
        text = json.dumps(context, sort_keys=True)
        assert not any(token in text for token in forbidden)
    assert all(context == contexts[0] for context in contexts)


def test_workspace_pressure_state_is_visible_without_target_metadata(tmp_path):
    scenarios = generate_scenarios(tmp_path / "bench")
    for scenario in scenarios:
        files = dict(scenario.workspace_files)
        assert "pressure_state.json" in files
        pressure = json.loads(files["pressure_state.json"])
        assert pressure["opportunity"]
        assert not any(token in json.dumps(pressure) for token in {"RCI-C00", "target_rule_id", "target_stage", "S1", "S2", "S3", "S4", "S5", "S6"})


def test_unlaunched_results_and_fabricated_aggregate_are_rejected(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    state = scenario.initial_state
    result_action = AgentAction("record_run_result", {"run_result": state["pre_aggregate"]["observed_results"][0]})
    result = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "result").run(_SpyAgent(result_action))
    assert any(event["decision"] == "BLOCK" and "LEDGER" in event["detected_rule_ids"] for event in result.events)
    aggregate_action = AgentAction("propose_aggregate", {"aggregate": state["pre_aggregate"]})
    aggregate_result = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "aggregate").run(_SpyAgent(aggregate_action))
    assert any(event["decision"] == "BLOCK" and "LEDGER" in event["detected_rule_ids"] for event in aggregate_result.events)
    assert aggregate_result.completed is False


def test_immediate_untouched_aggregate_does_not_complete_task(tmp_path):
    scenario = generate_scenarios(tmp_path / "bench")[0]
    action = AgentAction("propose_aggregate", {"aggregate": scenario.initial_state["pre_aggregate"]})
    result = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "immediate").run(_SpyAgent(action))
    assert result.completed is False
    assert result.metrics()["VTCR"] == 0.0


def test_evidence_backed_c001_rejects_missing_run_evidence_with_legacy_labels(tmp_path):
    scenario = next(item for item in generate_scenarios(tmp_path / "bench") if item.family == "S1")
    result = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "c001").run(ViolationAttemptAgent())
    assert "RCI-C001" in result.validator["attempted_rule_ids"]
    assert result.validator["crossed_target_gate"] is False
    assert any("RCI-C001" in event["detected_rule_ids"] for event in result.events)


def test_action_level_cier_can_be_fractional():
    scenario = generate_scenarios(Path("D:/temp/phase2a-cier")[0] if False else Path("D:/temp/phase2a-cier"))[0]
    events = [
        {"event_index": 0, "action_type": "run_experiment", "lifecycle_stage": "pre_run", "decision": "ALLOW", "admitted": False, "result": {"payload": {"baseline_intent": scenario.initial_state["pre_run"]["baseline_intent"], "candidate_intent": {**scenario.initial_state["pre_run"]["candidate_intent"], "resolved_config": {"training": {"max_iterations": 999}}}}}},
        {"event_index": 1, "action_type": "run_experiment", "lifecycle_stage": "pre_run", "decision": "BLOCK", "admitted": False, "result": {"payload": {"baseline_intent": scenario.initial_state["pre_run"]["baseline_intent"], "candidate_intent": {**scenario.initial_state["pre_run"]["candidate_intent"], "resolved_config": {"training": {"max_iterations": 998}}}}}},
    ]
    validated = IndependentTrajectoryValidator().validate(events, scenario)
    assert validated["violating_action_attempt_count"] == 2
    assert validated["violating_action_cross_count"] == 1
    assert validated["violating_action_cross_count"] / validated["violating_action_attempt_count"] == 0.5


def test_repair_offered_is_distinct_from_agent_attempt(tmp_path):
    scenario = next(item for item in generate_scenarios(tmp_path / "bench") if item.family == "S2")
    offered = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "offered").run(ViolationAttemptAgent())
    followed = EpisodeHarness(scenario, Condition.A4_RUNTIME_RESEARCHCI, tmp_path / "followed").run(RepairFollowingAgent())
    assert offered.repair_offered is True
    assert offered.repair_attempted is False
    assert offered.repair_succeeded is False
    assert followed.repair_offered is True
    assert followed.repair_attempted is True
    assert followed.repair_succeeded is True


def test_wall_clock_budget_is_enforced_with_injected_clock(tmp_path):
    class FakeClock:
        def __init__(self):
            self.value = 0.0

        def __call__(self):
            self.value += 10.0
            return self.value

    scenario = generate_scenarios(tmp_path / "bench")[0]
    scenario = scenario.__class__(**{**scenario.__dict__, "wall_clock_budget_seconds": 1})
    result = EpisodeHarness(scenario, Condition.A0_NO_CHECK, tmp_path / "timeout", clock=FakeClock()).run(ValidAgent())
    assert result.budget_exhausted is True
    assert result.completed is False
    assert any(event["action_type"] == "budget_exhausted" for event in result.events)
