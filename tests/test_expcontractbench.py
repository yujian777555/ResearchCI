from __future__ import annotations

import json
from pathlib import Path

from expcontractbench.generator import generate_benchmark
from expcontractbench.metrics import compute_metrics
from expcontractbench.runner import NoCheckAdapter, RuntimeResearchCIAdapter, evaluate_split
from expcontractbench.validator import validate_benchmark


def file_hashes(root: Path) -> dict[str, str]:
    import hashlib

    return {
        str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_generator_has_exact_frozen_cardinality_and_distribution(tmp_path):
    root = tmp_path / "bench"
    generate_benchmark(root)

    report = validate_benchmark(root)

    assert report["valid"] is True
    assert report["total_cases"] == 240
    assert report["split_counts"] == {"dev": 120, "locked": 120}
    assert report["label_counts"] == {"invalid": 180, "valid": 60}
    assert report["repo_counts"] == {
        "tabular_sklearn": 80,
        "vision_pytorch": 80,
        "text_classification": 80,
    }
    assert report["rule_counts"] == {f"RCI-C00{i}": 30 for i in range(1, 7)}
    assert report["reproducible"] is True


def test_generator_is_bit_for_bit_reproducible(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_benchmark(first)
    generate_benchmark(second)

    assert file_hashes(first) == file_hashes(second)


def test_case_ids_are_opaque_and_adapter_inputs_hide_ground_truth(tmp_path):
    root = tmp_path / "bench"
    generate_benchmark(root)
    manifests = [json.loads(line) for line in (root / "manifests" / "cases.jsonl").read_text().splitlines()]

    assert all(case["case_id"].startswith("case_") for case in manifests)
    assert all(not any(rule in case["case_id"] for rule in ("C001", "C002", "C003", "C004", "C005", "C006")) for case in manifests)
    case_dir = root / "cases" / manifests[0]["case_id"]
    inputs = json.dumps({str(path): path.read_text(errors="ignore") for path in (case_dir / "inputs").rglob("*") if path.is_file()})
    assert "target_rule_id" not in inputs
    assert "mutation_operator" not in inputs
    assert "ground_truth" not in inputs


def test_runtime_adapter_stops_at_first_block_and_nocheck_never_blocks(tmp_path):
    root = tmp_path / "bench"
    generate_benchmark(root)
    manifests = [json.loads(line) for line in (root / "manifests" / "cases.jsonl").read_text().splitlines()]
    invalid = next(case for case in manifests if case["split"] == "dev" and case["target_rule_id"] == "RCI-C002")
    case_dir = root / "cases" / invalid["case_id"]

    runtime = RuntimeResearchCIAdapter().check(case_dir)
    no_check = NoCheckAdapter().check(case_dir)

    assert runtime.runtime_decision == "BLOCK"
    assert runtime.blocked_stage == "pre_run"
    assert no_check.runtime_decision == "PASS"
    assert no_check.blocked_stage is None


def test_dev_evaluation_and_metrics_have_expected_shapes(tmp_path):
    root = tmp_path / "bench"
    generate_benchmark(root)
    predictions, truth = evaluate_split(root, "dev", RuntimeResearchCIAdapter())
    metrics = compute_metrics(predictions, truth)

    assert len(predictions) == 120
    assert len(truth) == 120
    for key in (
        "invalid_experiment_escape_rate",
        "prevention_rate",
        "violation_recall",
        "violation_precision",
        "false_block_rate",
        "rule_id_accuracy",
        "location_accuracy",
        "detection_stage_distribution",
        "runtime_overhead_ms",
        "prevented_invalid_work_units",
        "repair_eligibility_rate",
        "conditional_repair_success_rate",
    ):
        assert key in metrics


def test_metrics_toy_predictions_are_deterministic():
    truth = [
        {"case_id": "i", "label": "invalid", "target_rule_id": "RCI-C001", "target_stage": "pre_aggregate", "expected_locations": ["x"], "declared_cost_units": 5},
        {"case_id": "v", "label": "valid", "target_rule_id": None, "target_stage": None, "expected_locations": [], "declared_cost_units": 0},
    ]
    predictions = [
        {"case_id": "i", "runtime_decision": "BLOCK", "blocked_stage": "pre_aggregate", "detected_rule_ids": ["RCI-C001"], "detected_locations": ["x"], "elapsed_ms": 1.0, "repair_capability": "requires_reexecution"},
        {"case_id": "v", "runtime_decision": "PASS", "blocked_stage": None, "detected_rule_ids": [], "detected_locations": [], "elapsed_ms": 1.0, "repair_capability": None},
    ]

    metrics = compute_metrics(predictions, truth)

    assert metrics["invalid_experiment_escape_rate"] == 0.0
    assert metrics["prevention_rate"] == 1.0
    assert metrics["violation_recall"] == 1.0
    assert metrics["false_block_rate"] == 0.0
    assert metrics["rule_id_accuracy"] == 1.0
    assert metrics["prevented_invalid_work_units"] == 5
