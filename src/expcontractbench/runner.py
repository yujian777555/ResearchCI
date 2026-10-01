"""Runtime adapters and split evaluation; ground truth is joined outside adapters."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from researchci import (
    AggregateIntent,
    CacheConsumeIntent,
    CachedArtifactManifest,
    InvariantEngine,
    RunIntent,
    RunResult,
    parse_contract,
)


@dataclass
class AdapterResult:
    case_id: str
    adapter: str
    runtime_decision: str
    blocked_stage: str | None
    detected_rule_ids: list[str]
    detected_locations: list[str]
    stage_results: dict[str, Any]
    elapsed_ms: float
    repair_capability: str | None = None
    repair_attempted_count: int = 0
    repair_success_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        result = self.__dict__.copy()
        result["detection_stage"] = self.blocked_stage if self.detected_rule_ids else None
        result["escaped"] = False
        return result


def _load_case(case_dir: Path) -> tuple[Any, dict[str, Any]]:
    contract = parse_contract(case_dir / "inputs" / "contract.yaml")
    stages = {}
    for stage in ("pre_run", "pre_cache_consume", "pre_aggregate"):
        path = case_dir / "inputs" / f"{stage}.json"
        if path.exists():
            stages[stage] = json.loads(path.read_text(encoding="utf-8"))
    return contract, stages


def _aggregate(value: dict[str, Any]) -> AggregateIntent:
    return AggregateIntent(
        experiment_id=value["experiment_id"],
        baseline_run_ids=tuple(value["baseline_run_ids"]),
        candidate_run_ids=tuple(value["candidate_run_ids"]),
        declared_seed_set=tuple(value["declared_seed_set"]),
        aggregation_metric=value["aggregation_metric"],
        baseline_seed_set=tuple(value["baseline_seed_set"]) if value.get("baseline_seed_set") is not None else None,
        candidate_seed_set=tuple(value["candidate_seed_set"]) if value.get("candidate_seed_set") is not None else None,
        baseline_runs=tuple(RunIntent.from_mapping(item) for item in value.get("baseline_runs", [])),
        candidate_runs=tuple(RunIntent.from_mapping(item) for item in value.get("candidate_runs", [])),
        observed_results=tuple(RunResult.from_mapping(item) for item in value.get("observed_results", [])),
        included_run_ids=tuple(value.get("included_run_ids", [])),
        reported_failed_run_ids=tuple(value.get("reported_failed_run_ids", [])),
    )


class RuntimeResearchCIAdapter:
    name = "runtime_researchci"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        contract, stages = _load_case(case_dir)
        engine = InvariantEngine()
        stage_results: dict[str, Any] = {}
        detected_ids: list[str] = []
        locations: list[str] = []
        blocked_stage = None
        decision = "PASS"
        repair_attempted = 0
        repair_success = 0

        def check_stage(stage: str, payload: dict):
            if stage == "pre_run":
                return engine.check_pre_run(contract, RunIntent.from_mapping(payload["baseline_intent"]), RunIntent.from_mapping(payload["candidate_intent"]))
            if stage == "pre_cache_consume":
                return engine.check_pre_cache_consume(contract, CacheConsumeIntent(current_run=RunIntent.from_mapping(payload["current_run"]), cached_artifact=CachedArtifactManifest(**payload["cached_artifact"])))
            return engine.check_pre_aggregate(contract, _aggregate(payload))

        def apply_auto_repairs(stage: str, payload: dict, result):
            nonlocal repair_attempted, repair_success
            eligible = [v for v in result.violations if v.repair.get("operation") in {"set", "report_failed_run"}]
            if not eligible:
                return
            repair_attempted += len(eligible)
            repaired = deepcopy(payload)
            for violation in eligible:
                repair = violation.repair
                if repair["operation"] == "set" and stage == "pre_run":
                    path = repair["path"]
                    if path.startswith("candidate."):
                        current = repaired["candidate_intent"]["resolved_config"]
                        parts = path[len("candidate."):].split(".")
                        for part in parts[:-1]:
                            current = current[part]
                        current[parts[-1]] = repair["value"]
                elif repair["operation"] == "report_failed_run" and stage == "pre_aggregate":
                    repaired["reported_failed_run_ids"].append(repair["run_id"])
            if check_stage(stage, repaired).decision == "PASS":
                repair_success += len(eligible)
        for stage in ("pre_run", "pre_cache_consume", "pre_aggregate"):
            if stage not in stages:
                continue
            payload = stages[stage]
            result = check_stage(stage, payload)
            stage_results[stage] = result.as_dict()
            if result.decision == "BLOCK":
                decision = "BLOCK"
                blocked_stage = stage
                detected_ids = [item.rule_id for item in result.violations]
                locations = [item.location for item in result.violations]
                apply_auto_repairs(stage, payload, result)
                break
        return AdapterResult(
            case_id=case_dir.name,
            adapter=self.name,
            runtime_decision=decision,
            blocked_stage=blocked_stage,
            detected_rule_ids=detected_ids,
            detected_locations=locations,
            stage_results=stage_results,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 6),
            repair_attempted_count=repair_attempted,
            repair_success_count=repair_success,
        )


class NoCheckAdapter:
    name = "no_check"

    def check(self, case_dir: Path) -> AdapterResult:
        return AdapterResult(case_dir.name, self.name, "PASS", None, [], [], {}, 0.0, None, 0, 0)


def evaluate_split(root: str | Path, split: str, adapter) -> tuple[list[dict], list[dict]]:
    root = Path(root)
    manifests = [json.loads(line) for line in (root / "manifests" / "cases.jsonl").read_text().splitlines() if line.strip()]
    predictions = []
    for manifest in sorted((item for item in manifests if item["split"] == split), key=lambda item: item["case_id"]):
        result = adapter.check(root / "cases" / manifest["case_id"])
        predictions.append(result.as_dict())
    truths = {json.loads(line)["case_id"]: json.loads(line) for line in (root / "manifests" / "ground_truth.jsonl").read_text().splitlines() if line.strip()}
    selected_truth = [truths[manifest["case_id"]] for manifest in sorted((item for item in manifests if item["split"] == split), key=lambda item: item["case_id"])]
    return predictions, selected_truth
