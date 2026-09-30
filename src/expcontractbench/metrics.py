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
    precision_hits = 0
    rule_exact = 0
    location_exact = 0
    false_blocks = 0
    stages: Counter[str] = Counter()
    prevented_units = 0
    eligible = 0
    eligible_success = 0
    for item in truth:
        pred = by_id[item["case_id"]]
        if pred["blocked_stage"]:
            stages[pred["blocked_stage"]] += 1
        if item["label"] == "invalid":
            is_blocked = pred["runtime_decision"] == "BLOCK"
            if is_blocked:
                blocked.append(item)
                prevented_units += int(item.get("declared_cost_units", 0))
            else:
                escaped.append(item)
            target = set(item.get("expected_rule_ids") or ([item["target_rule_id"]] if item.get("target_rule_id") else []))
            detected = set(pred["detected_rule_ids"])
            recall_hits += int(bool(target & detected))
            precision_hits += int(bool(detected & target))
            rule_exact += int(detected == target)
            location_exact += int(set(item.get("expected_locations", [])) >= set(pred["detected_locations"]) and bool(pred["detected_locations"]))
            if item.get("repair_capability") == "auto_repairable":
                eligible += 1
                eligible_success += int(bool(pred["detected_rule_ids"]))
        else:
            false_blocks += int(pred["runtime_decision"] == "BLOCK")
    total_invalid = len(invalid)
    total_valid = len(valid)
    elapsed = [float(item.get("elapsed_ms", 0.0)) for item in predictions]
    return {
        "invalid_experiment_escape_rate": len(escaped) / total_invalid if total_invalid else 0.0,
        "prevention_rate": len(blocked) / total_invalid if total_invalid else 0.0,
        "violation_recall": recall_hits / total_invalid if total_invalid else 0.0,
        "violation_precision": precision_hits / total_invalid if total_invalid else 0.0,
        "false_block_rate": false_blocks / total_valid if total_valid else 0.0,
        "rule_id_accuracy": rule_exact / total_invalid if total_invalid else 0.0,
        "location_accuracy": location_exact / total_invalid if total_invalid else 0.0,
        "detection_stage_distribution": dict(sorted(stages.items())),
        "runtime_overhead_ms": sum(elapsed) / len(elapsed) if elapsed else 0.0,
        "prevented_invalid_work_units": prevented_units,
        "repair_eligibility_rate": eligible / total_invalid if total_invalid else 0.0,
        "conditional_repair_success_rate": eligible_success / eligible if eligible else None,
        "case_count": len(truth),
    }
