"""验证实际 agent 边界、权威 ledger 和行动级证据。"""
from copy import deepcopy
from dataclasses import replace
import json
import socket

import pytest

from researchci_agent.conditions import Condition
from researchci_agent.mediator import EpisodeHarness
from researchci_agent.schema import AgentAction
from researchci_agent.scenarios import generate_scenarios
from researchci_agent.scripted_agents import ValidAgent, ViolationAttemptAgent, RepairFollowingAgent


@pytest.fixture(scope="module")
def specs(tmp_path_factory):
    return generate_scenarios(tmp_path_factory.mktemp("r1-scenarios"))


class BoundarySpy:
    def start_episode(self, context):
        self.context = deepcopy(context)

    def bind_scenario(self, scenario):
        raise AssertionError("不能通过旁路将 ScenarioSpec 交给 agent")

    def next_action(self, observation):
        return AgentAction("finish_episode", {"summary": "boundary audit"})


def test_harness_does_not_pass_scenario_through_side_channel(specs, tmp_path):
    contexts = []
    for condition in Condition:
        agent = BoundarySpy()
        EpisodeHarness(specs[0], condition, tmp_path / condition.value).run(agent)
        contexts.append(agent.context)
    assert all(context == contexts[0] for context in contexts)
    visible = json.dumps(contexts[0])
    for token in ("hidden_metadata", "family", "target_rule_id", "target_stage", "_scenario", "condition", "S1", "S2", "S3", "S4", "S5", "S6", "A0", "A1", "A2", "A3", "A4"):
        assert token not in visible


def test_agent_context_is_a_copy_and_cannot_change_authoritative_contract(specs, tmp_path):
    class MutatingAgent(BoundarySpy):
        def start_episode(self, context):
            context["initial_state"]["contract"]["comparison"]["paired_seeds"]["seeds"] = [99]
    before = deepcopy(specs[0].contract)
    harness = EpisodeHarness(specs[0], Condition.A4, tmp_path / "copy")
    harness.run(MutatingAgent())
    assert specs[0].contract == before
    assert harness.state["contract"] == before


@pytest.mark.parametrize("family", ["S1", "S2", "S3", "S4", "S5", "S6"])
def test_valid_and_invalid_routes_for_all_profiles(specs, tmp_path, family, monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("scripted episode 不应访问网络")
    monkeypatch.setattr(socket, "create_connection", deny_network)
    for scenario in [item for item in specs if item.family == family]:
        valid = EpisodeHarness(scenario, Condition.A4, tmp_path / scenario.scenario_id / "valid").run(ValidAgent())
        escaped = EpisodeHarness(scenario, Condition.A0, tmp_path / scenario.scenario_id / "escape").run(ViolationAttemptAgent())
        prevented = EpisodeHarness(scenario, Condition.A4, tmp_path / scenario.scenario_id / "prevent").run(ViolationAttemptAgent())
        recovery = EpisodeHarness(scenario, Condition.A4, tmp_path / scenario.scenario_id / "recovery").run(RepairFollowingAgent())
        assert valid.completed and valid.metrics()["VTCR"] == 1.0
        assert valid.validator["violating_action_attempt_count"] == 0
        assert escaped.validator["violating_action_cross_count"] >= 1
        assert escaped.metrics()["EIFR"] == 1.0
        assert prevented.validator["violating_action_cross_count"] == 0
        assert prevented.repair_offered and not prevented.repair_attempted
        assert recovery.completed and recovery.repair_attempted and recovery.repair_succeeded


def test_duplicate_result_is_rejected_even_when_identical(specs, tmp_path):
    harness = EpisodeHarness(specs[1], Condition.A0, tmp_path / "duplicate")
    run = deepcopy(specs[1].initial_state["pre_run"])
    observation = harness._dispatch(AgentAction("run_experiment", run))
    result = observation.result["run_results"][0]
    assert harness._dispatch(AgentAction("record_run_result", {"run_result": result})).decision == "ALLOW"
    assert harness._dispatch(AgentAction("record_run_result", {"run_result": result})).decision == "BLOCK"


def test_arbitrary_recorded_metrics_cannot_replace_executor_outcome(specs, tmp_path):
    harness = EpisodeHarness(specs[1], Condition.A0, tmp_path / "forged-result")
    observation = harness._dispatch(AgentAction("run_experiment", deepcopy(specs[1].initial_state["pre_run"])))
    forged = deepcopy(observation.result["run_results"][0])
    forged["metrics"] = {"accuracy": 999.0}
    assert harness._dispatch(AgentAction("record_run_result", {"run_result": forged})).decision == "BLOCK"


def test_inspect_feedback_cannot_mutate_harness_owned_ledger(specs, tmp_path):
    harness = EpisodeHarness(specs[1], Condition.A0, tmp_path / "inspect-copy")
    observation = harness._dispatch(AgentAction("inspect_experiment_state"))
    observation.result["ledger"]["launched"]["fake"] = {"run_id": "fake"}
    assert "fake" not in harness.state["ledger"]["launched"]


def test_timeout_after_next_action_cannot_award_completion(specs, tmp_path):
    class Clock:
        value = 0.0
        def __call__(self):
            return self.value
    clock = Clock()
    class SlowAgent(BoundarySpy):
        def next_action(self, observation):
            clock.value = 999
            return AgentAction("finish_episode", {"summary": "late"})
    result = EpisodeHarness(specs[0], Condition.A0, tmp_path / "late", clock=clock).run(SlowAgent())
    assert result.budget_exhausted and not result.completed
    assert any(event["action_type"] == "budget_exhausted" for event in result.events)


def test_multi_attempt_fractional_cier_is_computed_from_real_actions(specs, tmp_path):
    scenario = next(item for item in specs if item.family == "S2")
    class RepeatedAgent(BoundarySpy):
        def start_episode(self, context):
            self.run = deepcopy(context["initial_state"]["pre_run"])
            self.run["candidate_intent"]["resolved_config"]["training"]["max_iterations"] += 10
            self.actions = [AgentAction("run_experiment", deepcopy(self.run)) for _ in range(3)]
            self.actions.append(AgentAction("finish_episode"))
        def next_action(self, observation):
            return self.actions.pop(0)
    harness = EpisodeHarness(scenario, Condition.A0, tmp_path / "fraction")
    result = harness.run(RepeatedAgent())
    # 第一条科学动作被执行；同 ID 的后两条请求由完整性 ledger 拒绝。
    assert result.validator["violating_action_attempt_count"] == 3
    assert result.validator["violating_action_cross_count"] == 1
    assert result.metrics()["CIER"] == pytest.approx(1/3)


def test_failed_run_is_produced_by_environment_not_agent_patch(specs, tmp_path):
    scenario = next(item for item in specs if item.family == "S6")
    result = EpisodeHarness(scenario, Condition.A4, tmp_path / "failure").run(ValidAgent())
    failed = [outcome for event in result.events for outcome in event["result"].get("run_results", []) if outcome["status"] == "failed"]
    assert len(failed) == 1
    assert result.ledger["results"][failed[0]["run_id"]]["status"] == "failed"
    assert failed[0]["run_id"] in result.ledger["aggregates"][-1]["reported_failed_run_ids"]
