from copy import deepcopy

import pytest

from expcontractbench.metrics import compute_metrics
from expcontractbench.profiles import profiles


def toy():
    truth = [
        {"case_id": "i", "label": "invalid", "target_rule_id": "RCI-C002",
         "target_stage": "pre_run", "expected_rule_ids": ["RCI-C002"],
         "expected_locations": ["x", "y"], "declared_cost_units": 5,
         "repair_capability": "auto_repairable"},
        {"case_id": "v", "label": "valid", "target_rule_id": None,
         "expected_rule_ids": [], "expected_locations": [], "declared_cost_units": 0},
    ]
    predictions = [
        {"case_id": "i", "runtime_decision": "BLOCK", "blocked_stage": "pre_run",
         "detected_rule_ids": ["RCI-C002"], "detected_locations": ["x", "y"], "elapsed_ms": 1},
        {"case_id": "v", "runtime_decision": "PASS", "blocked_stage": None,
         "detected_rule_ids": [], "detected_locations": [], "elapsed_ms": 1},
    ]
    return predictions, truth


def test_precision_penalizes_extra_wrong_rule_and_deduplicates_same_rule():
    predictions, truth = toy()
    predictions[0]["detected_rule_ids"] = ["RCI-C002", "RCI-C002", "RCI-C004"]
    assert compute_metrics(predictions, truth)["violation_precision"] == 0.5


def test_precision_penalizes_detection_on_valid_case():
    predictions, truth = toy()
    predictions[1]["detected_rule_ids"] = ["RCI-C001"]
    predictions[1]["runtime_decision"] = "BLOCK"
    predictions[1]["blocked_stage"] = "pre_aggregate"
    metrics = compute_metrics(predictions, truth)
    assert metrics["violation_precision"] == 0.5
    assert metrics["false_block_rate"] == 1.0


def test_location_accuracy_requires_exact_set():
    predictions, truth = toy()
    predictions[0]["detected_locations"] = ["x"]
    assert compute_metrics(predictions, truth)["location_accuracy"] == 0.0


def test_detecting_auto_repairable_rule_is_not_successful_repair():
    predictions, truth = toy()
    metrics = compute_metrics(predictions, truth)
    assert metrics["attempted_auto_repair_count"] == 0
    assert metrics["successful_auto_repair_count"] == 0
    assert metrics["conditional_repair_success_rate"] is None


def test_reexecution_and_manual_cases_are_not_auto_repair_failures():
    predictions, truth = toy()
    truth[0]["repair_capability"] = "manual_resolution"
    assert compute_metrics(predictions, truth)["repair_eligibility_rate"] == 0


def test_late_block_does_not_prevent_target_gate_escape():
    predictions, truth = toy()
    predictions[0]["blocked_stage"] = "pre_aggregate"
    metrics = compute_metrics(predictions, truth)
    assert metrics["invalid_experiment_escape_rate"] == 1
    assert metrics["prevented_invalid_work_units"] == 0


def test_profiles_have_twenty_scientifically_distinct_controls():
    from expcontractbench.canonical import sha256_value

    schemas = []
    for profile in profiles():
        controls = [profile.base_case(index) for index in range(20)]
        # 剔除索引与名称，仅比较会影响 checker 的科学输入。
        states = [{stage: case[stage] for stage in (
            "pre_run", "pre_cache_consume", "pre_aggregate"
        )} for case in controls]
        assert len({sha256_value(state) for state in states}) == 20
        schemas.append(profile.contract()["comparison"]["equal_budget_fields"])
    assert len({tuple(schema) for schema in schemas}) == 3
