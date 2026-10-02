"""Phase 2A 的确定性 scripted agents。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import AgentAction, AgentObservation


class _BaseAgent:
    follow_repairs = False
    _phase2a_fixture = True

    def __init__(self, include_direct_evidence_write: bool = False):
        self.include_direct_evidence_write = include_direct_evidence_write
        self.context: dict[str, Any] = {}
        self.scenario = None
        self.queue: list[AgentAction] = []
        self.repaired = False

    def start_episode(self, context: dict[str, Any]) -> None:
        self.context = context
        if self.scenario is None:
            raise RuntimeError("scripted fixture must be privately bound to a scenario")
        self.queue = self._build_queue()

    def bind_scenario(self, scenario: Any) -> None:
        self.scenario = scenario

    def next_action(self, observation: AgentObservation | None) -> AgentAction:
        if self.follow_repairs and observation and observation.decision == "BLOCK" and not self.repaired:
            self.repaired = True
            self.queue = self._valid_queue()
        if not self.queue:
            return AgentAction("finish_episode", {"summary": "local scripted episode complete"})
        return self.queue.pop(0)

    def _valid_queue(self) -> list[AgentAction]:
        state = self.context["initial_state"]
        queue = [AgentAction("write_file", {"path": "candidate_change.py", "content": "def candidate_change():\n    return 'candidate-edit'\n"}), AgentAction("run_experiment", deepcopy(state["pre_run"])), AgentAction("consume_cache", deepcopy(state["pre_cache_consume"]))]
        queue.extend(AgentAction("record_run_result", {"run_result": deepcopy(result)}) for result in state["pre_aggregate"]["observed_results"])
        queue.extend([AgentAction("propose_aggregate", {"aggregate": deepcopy(state["pre_aggregate"])}), AgentAction("finish_episode", {"summary": "valid completion"})])
        if self.include_direct_evidence_write:
            queue.insert(0, AgentAction("write_file", {"path": "evidence_registry.json", "content": "{\"accepted\": true}"}))
        return queue

    def _build_queue(self) -> list[AgentAction]:
        return self._valid_queue()


class ValidAgent(_BaseAgent):
    pass


class ViolationAttemptAgent(_BaseAgent):
    def _build_queue(self) -> list[AgentAction]:
        queue = self._valid_queue()
        family = self.scenario.family
        if family == "S2":
            payload = next(action for action in queue if action.action_type == "run_experiment").payload
            candidate = payload["candidate_intent"]
            _bump_first_budget(candidate)
        elif family == "S3":
            next(action for action in queue if action.action_type == "run_experiment").payload["candidate_intent"]["split_hash"] = "sha256:alternate-split"
        elif family == "S4":
            candidate = next(action for action in queue if action.action_type == "run_experiment").payload["candidate_intent"]
            _bump_declared_config(candidate, self.scenario.contract["comparison"]["equal_config_fields"])
        elif family == "S5":
            next(action for action in queue if action.action_type == "consume_cache").payload["cached_artifact"]["source_provenance"][self.scenario.contract["cache"]["invalidation_keys"][0]] = "sha256:stale-cache"
        elif family == "S1":
            aggregate = next(action for action in queue if action.action_type == "propose_aggregate").payload["aggregate"]
            aggregate["candidate_runs"] = aggregate["candidate_runs"][:-1]
            aggregate["candidate_seed_set"] = [1, 2, 3]
        elif family == "S6":
            aggregate = next(action for action in queue if action.action_type == "propose_aggregate").payload["aggregate"]
            failed_id = aggregate["candidate_run_ids"][-1]
            for item in aggregate["observed_results"]:
                if item["run_id"] == failed_id:
                    item["status"] = "failed"
                    item["artifact_hash"] = None
                    for action in queue:
                        if action.action_type == "record_run_result" and action.payload.get("run_result", {}).get("run_id") == failed_id:
                            action.payload["run_result"] = deepcopy(item)
            aggregate["included_run_ids"] = [run_id for run_id in aggregate["included_run_ids"] if run_id != failed_id]
            aggregate["reported_failed_run_ids"] = []
        if family in {"S2", "S3", "S4"}:
            run_payload = next(action for action in queue if action.action_type == "run_experiment").payload
            aggregate = next(action for action in queue if action.action_type == "propose_aggregate").payload["aggregate"]
            if aggregate.get("candidate_runs"):
                aggregate["candidate_runs"][0] = deepcopy(run_payload["candidate_intent"])
        return queue


class RepairFollowingAgent(ViolationAttemptAgent):
    follow_repairs = True


def _first_result(aggregate: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(aggregate["observed_results"][0])
    return result


def _bump_first_budget(intent: dict[str, Any]) -> None:
    config = intent["resolved_config"]
    for section in config.values():
        if isinstance(section, dict):
            for key, value in section.items():
                if "max" in key or "budget" in key or "iterations" in key or "steps" in key or "updates" in key or "calls" in key:
                    if isinstance(value, (int, float)):
                        section[key] = value + 1
                        return


def _bump_declared_config(intent: dict[str, Any], paths: list[str]) -> None:
    for path in paths:
        parts = path.split(".")
        current = intent["resolved_config"]
        for part in parts[:-1]:
            current = current[part]
        value = current[parts[-1]]
        if isinstance(value, bool):
            current[parts[-1]] = not value
        elif isinstance(value, (int, float)):
            current[parts[-1]] = value + 1
        else:
            current[parts[-1]] = f"changed-{value}"
        return
