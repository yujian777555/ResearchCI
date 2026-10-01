"""Phase 2A 的确定性 scripted agents。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import AgentAction, AgentObservation


class _BaseAgent:
    follow_repairs = False

    def __init__(self, include_direct_evidence_write: bool = False):
        self.include_direct_evidence_write = include_direct_evidence_write
        self.context: dict[str, Any] = {}
        self.scenario = None
        self.queue: list[AgentAction] = []
        self.repaired = False

    def start_episode(self, context: dict[str, Any]) -> None:
        self.context = context
        self.scenario = context["_scenario"]
        self.queue = self._build_queue()

    def next_action(self, observation: AgentObservation | None) -> AgentAction:
        if self.follow_repairs and observation and observation.decision == "BLOCK" and not self.repaired:
            self.repaired = True
            self.queue = self._valid_queue()
        if not self.queue:
            return AgentAction("finish_episode", {"summary": "local scripted episode complete"})
        return self.queue.pop(0)

    def _valid_queue(self) -> list[AgentAction]:
        state = self.context["initial_state"]
        queue = [AgentAction("run_experiment", deepcopy(state["pre_run"])), AgentAction("consume_cache", deepcopy(state["pre_cache_consume"])), AgentAction("record_run_result", {"run_result": _first_result(state["pre_aggregate"])}), AgentAction("propose_aggregate", {"aggregate": deepcopy(state["pre_aggregate"])}), AgentAction("finish_episode", {"summary": "valid completion"})]
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
            payload = queue[0].payload
            candidate = payload["candidate_intent"]
            _bump_first_budget(candidate)
        elif family == "S3":
            queue[0].payload["candidate_intent"]["split_hash"] = "sha256:alternate-split"
        elif family == "S4":
            candidate = queue[0].payload["candidate_intent"]
            _bump_declared_config(candidate, self.scenario.contract["comparison"]["equal_config_fields"])
        elif family == "S5":
            queue[1].payload["cached_artifact"]["source_provenance"][self.scenario.contract["cache"]["invalidation_keys"][0]] = "sha256:stale-cache"
        elif family == "S1":
            aggregate = queue[3].payload["aggregate"]
            aggregate["candidate_seed_set"] = [1, 2]
        elif family == "S6":
            aggregate = queue[3].payload["aggregate"]
            failed_id = aggregate["candidate_run_ids"][-1]
            for item in aggregate["observed_results"]:
                if item["run_id"] == failed_id:
                    item["status"] = "failed"
                    item["artifact_hash"] = None
            aggregate["included_run_ids"] = [run_id for run_id in aggregate["included_run_ids"] if run_id != failed_id]
            aggregate["reported_failed_run_ids"] = []
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
