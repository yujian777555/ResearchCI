"""Deterministic benchmark metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any


def compute_metrics(predictions: list[dict], truth: list[dict]) -> dict[str, Any]:
    by_id = {item["case_id"]: item for item in predictions}
    invalid = [item for item in truth if item["label"] == "invalid"]
    valid = [item for item in truth if item["label"] == "valid"]
    escaped = []
    blocked = []
    recall_hits = 0
    true_positive_rules = 0
    false_positive_rules = 0
    rule_exact = 0
    location_exact = 0
    false_blocks = 0
    stages: Counter[str] = Counter()
    prevented_units = 0
    eligible = 0
    attempted_repairs = 0
    successful_repairs = 0
    stage_order = {"pre_run": 0, "pre_cache_consume": 1, "pre_aggregate": 2}
    for item in truth:
        pred = by_id[item["case_id"]]
        if pred["blocked_stage"]:
            stages[pred["blocked_stage"]] += 1
        if item["label"] == "invalid":
            is_blocked = pred["runtime_decision"] == "BLOCK" and stage_order.get(pred.get("blocked_stage"), 99) <= stage_order.get(item.get("target_stage"), 99)
            if is_blocked:
                blocked.append(item)
                prevented_units += int(item.get("declared_cost_units", 0))
            else:
                escaped.append(item)
            target = set(item.get("expected_rule_ids") or ([item["target_rule_id"]] if item.get("target_rule_id") else []))
            detected = set(pred["detected_rule_ids"])
            recall_hits += int(bool(target & detected))
            true_positive_rules += len(detected & target)
            false_positive_rules += len(detected - target)
            rule_exact += int(detected == target)
            location_exact += int(set(item.get("expected_locations", [])) == set(pred["detected_locations"]))
            if item.get("repair_capability") == "auto_repairable":
                eligible += 1
                attempted_repairs += int(pred.get("repair_attempted_count", 0))
                successful_repairs += int(pred.get("repair_success_count", 0))
        else:
            false_blocks += int(pred["runtime_decision"] == "BLOCK")
            false_positive_rules += len(set(pred["detected_rule_ids"]))
    total_invalid = len(invalid)
    total_valid = len(valid)
    elapsed = [float(item.get("elapsed_ms", 0.0)) for item in predictions]
    return {
        "invalid_experiment_escape_rate": len(escaped) / total_invalid if total_invalid else 0.0,
        "prevention_rate": len(blocked) / total_invalid if total_invalid else 0.0,
        "violation_recall": recall_hits / total_invalid if total_invalid else 0.0,
        "violation_precision": true_positive_rules / (true_positive_rules + false_positive_rules) if (true_positive_rules + false_positive_rules) else 0.0,
        "false_block_rate": false_blocks / total_valid if total_valid else 0.0,
        "rule_id_accuracy": rule_exact / total_invalid if total_invalid else 0.0,
        "location_accuracy": location_exact / total_invalid if total_invalid else 0.0,
        "detection_stage_distribution": dict(sorted(stages.items())),
        "runtime_overhead_ms": sum(elapsed) / len(elapsed) if elapsed else 0.0,
        "prevented_invalid_work_units": prevented_units,
        "repair_eligibility_rate": eligible / total_invalid if total_invalid else 0.0,
        "attempted_auto_repair_count": attempted_repairs,
        "successful_auto_repair_count": successful_repairs,
        "conditional_repair_success_rate": successful_repairs / attempted_repairs if attempted_repairs else None,
        "case_count": len(truth),
    }
