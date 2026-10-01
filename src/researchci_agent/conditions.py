"""Phase 1E 等价的五种 episode condition 适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from researchci import AggregateIntent, CacheConsumeIntent, CachedArtifactManifest, InvariantEngine, RunIntent, parse_contract

from expcontractbench.runner import _aggregate


class Condition(str, Enum):
    A0_NO_CHECK = "A0_no_check"
    A1_SCHEMA_VALIDATION = "A1_schema_validation"
    A2_PROVENANCE_ONLY = "A2_provenance_only"
    A3_POSTHOC_RESEARCHCI = "A3_posthoc_researchci"
    A4_RUNTIME_RESEARCHCI = "A4_runtime_researchci"
    A0 = A0_NO_CHECK
    A1 = A1_SCHEMA_VALIDATION
    A2 = A2_PROVENANCE_ONLY
    A3 = A3_POSTHOC_RESEARCHCI
    A4 = A4_RUNTIME_RESEARCHCI


@dataclass(frozen=True)
class ConditionDecision:
    decision: str
    detected_rule_ids: tuple[str, ...] = ()
    repair: dict[str, Any] | None = None
    message: str = ""
    posthoc: tuple[dict[str, Any], ...] = ()


class ConditionAdapter:
    """把条件名称封装为可注入 mediator 的纯本地 adapter。"""

    def __init__(self, condition: Condition):
        self.condition = Condition(condition)

    def evaluate(self, contract: dict[str, Any], action_type: str, payload: dict[str, Any]) -> ConditionDecision:
        return decide(self.condition, contract, action_type, payload)


def _schema_check(action_type: str, payload: dict[str, Any]) -> ConditionDecision:
    try:
        if action_type == "run_experiment":
            RunIntent.from_mapping(payload["baseline_intent"])
            RunIntent.from_mapping(payload["candidate_intent"])
        elif action_type == "consume_cache":
            RunIntent.from_mapping(payload["current_run"])
            CachedArtifactManifest(**payload["cached_artifact"])
        elif action_type == "propose_aggregate":
            _aggregate(payload["aggregate"])
        elif action_type == "record_run_result":
            from researchci import RunResult

            RunResult.from_mapping(payload["run_result"])
        return ConditionDecision("ALLOW")
    except (ValueError, KeyError, TypeError) as exc:
        return ConditionDecision("BLOCK", ("SCHEMA",), {"operation": "fix_schema"}, str(exc))


def _runtime_decision(contract_mapping: dict[str, Any], action_type: str, payload: dict[str, Any]) -> ConditionDecision:
    contract = parse_contract(contract_mapping)
    engine = InvariantEngine()
    if action_type == "run_experiment":
        result = engine.check_pre_run(contract, RunIntent.from_mapping(payload["baseline_intent"]), RunIntent.from_mapping(payload["candidate_intent"]))
    elif action_type == "consume_cache":
        result = engine.check_pre_cache_consume(contract, CacheConsumeIntent(current_run=RunIntent.from_mapping(payload["current_run"]), cached_artifact=CachedArtifactManifest(**payload["cached_artifact"])))
    elif action_type == "propose_aggregate":
        result = engine.check_pre_aggregate(contract, _aggregate(payload["aggregate"]))
    else:
        return ConditionDecision("ALLOW")
    if result.decision == "PASS":
        return ConditionDecision("ALLOW")
    violations = [item.as_dict() for item in result.violations]
    return ConditionDecision("BLOCK", tuple(item["rule_id"] for item in violations), violations[0].get("repair"), violations[0].get("message", ""))


def decide(condition: Condition, contract: dict[str, Any], action_type: str, payload: dict[str, Any]) -> ConditionDecision:
    if action_type not in {"run_experiment", "consume_cache", "propose_aggregate"}:
        return _schema_check(action_type, payload) if condition == Condition.A1_SCHEMA_VALIDATION else ConditionDecision("ALLOW")
    if condition == Condition.A0_NO_CHECK:
        return ConditionDecision("ALLOW")
    if condition == Condition.A1_SCHEMA_VALIDATION:
        return _schema_check(action_type, payload)
    if condition == Condition.A2_PROVENANCE_ONLY:
        schema = _schema_check(action_type, payload)
        if schema.decision == "BLOCK":
            return schema
        if action_type != "consume_cache":
            return ConditionDecision("ALLOW")
        parsed_contract = parse_contract(contract)
        current = RunIntent.from_mapping(payload["current_run"])
        cached = CachedArtifactManifest(**payload["cached_artifact"])
        for key in parsed_contract.cache_invalidation_keys:
            if cached.source_provenance.get(key) != getattr(current, key, None):
                return ConditionDecision("BLOCK", ("RCI-C005",), {"operation": "invalidate_and_recompute", "artifact_id": cached.artifact_id, "mismatched_key": key}, "declared cache provenance mismatch")
        return ConditionDecision("ALLOW")
    if condition == Condition.A3_POSTHOC_RESEARCHCI:
        runtime = _runtime_decision(contract, action_type, payload)
        if runtime.decision == "BLOCK":
            return ConditionDecision("ALLOW", (), None, "action admitted; finding deferred to post-hoc observation", runtime_to_posthoc(runtime))
        return runtime
    return _runtime_decision(contract, action_type, payload)


def runtime_to_posthoc(decision: ConditionDecision) -> tuple[dict[str, Any], ...]:
    return ({"detected_rule_ids": list(decision.detected_rule_ids), "repair": decision.repair, "message": decision.message},)
