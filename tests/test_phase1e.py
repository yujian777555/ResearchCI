from __future__ import annotations

import inspect
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from expcontractbench import phase1e, runner
from expcontractbench.metrics import compute_metrics

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks" / "expcontractbench_v0_1"


@pytest.fixture(scope="module")
def dev_cases():
    records = [json.loads(line) for line in (BENCHMARK_ROOT / "manifests" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    return [record for record in records if record["split"] == "dev"]


@pytest.mark.parametrize("rule", [f"RCI-C00{i}" for i in range(1, 7)])
def test_schema_passes_schema_valid_semantic_violations(dev_cases, monkeypatch, rule):
    def forbidden_engine(*args, **kwargs):
        raise AssertionError("schema adapter 不得调用语义 engine")

    monkeypatch.setattr(phase1e, "InvariantEngine", forbidden_engine)
    case = next(item for item in dev_cases if item["target_rule_id"] == rule)
    result = phase1e.SchemaValidationAdapter().check(BENCHMARK_ROOT / "cases" / case["case_id"])
    assert result.runtime_decision == "PASS"
    assert result.detected_rule_ids == []
    assert "InvariantEngine" not in inspect.getsource(phase1e.SchemaValidationAdapter)
    assert "researchci.rules" not in inspect.getsource(phase1e.SchemaValidationAdapter)


@pytest.mark.parametrize("rule", ["RCI-C001", "RCI-C002", "RCI-C003", "RCI-C004", "RCI-C006"])
def test_provenance_does_not_enforce_other_semantics(dev_cases, monkeypatch, rule):
    def forbidden_engine(*args, **kwargs):
        raise AssertionError("provenance adapter 不得调用语义 engine")

    monkeypatch.setattr(phase1e, "InvariantEngine", forbidden_engine)
    case = next(item for item in dev_cases if item["target_rule_id"] == rule)
    result = phase1e.ProvenanceOnlyAdapter().check(BENCHMARK_ROOT / "cases" / case["case_id"])
    assert result.runtime_decision == "PASS"
    assert result.detected_rule_ids == []
    assert "InvariantEngine" not in inspect.getsource(phase1e.ProvenanceOnlyAdapter)


def test_provenance_only_uses_explicit_keys(dev_cases, tmp_path):
    case = next(item for item in dev_cases if item["label"] == "valid")
    case_dir = tmp_path / case["case_id"]
    shutil.copytree(BENCHMARK_ROOT / "cases" / case["case_id"] / "inputs", case_dir / "inputs")
    contract_path = case_dir / "inputs" / "contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    payload_path = case_dir / "inputs" / "pre_cache_consume.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["cached_artifact"]["source_provenance"]["environment_hash"] = "sha256:stale"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    assert phase1e.ProvenanceOnlyAdapter().check(case_dir).runtime_decision == "PASS"
    contract["cache"]["invalidation_keys"].append("environment_hash")
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    result = phase1e.ProvenanceOnlyAdapter().check(case_dir)
    assert result.runtime_decision == "BLOCK"
    assert result.detected_locations == ["environment_hash"]


def test_posthoc_detects_after_all_gates_without_prevention_or_repair(dev_cases):
    case = next(item for item in dev_cases if item["target_rule_id"] == "RCI-C002")
    prediction = phase1e.PosthocResearchCIAdapter().check(BENCHMARK_ROOT / "cases" / case["case_id"]).as_dict()
    assert prediction["detection_stage"] == "post_hoc"
    assert set(prediction["stage_results"]) == {"pre_run", "pre_cache_consume", "pre_aggregate"}
    assert prediction["detected_rule_ids"] == ["RCI-C002"]
    metrics = compute_metrics([prediction], [case])
    assert metrics["violation_recall"] == 1.0
    assert metrics["invalid_experiment_escape_rate"] == 1.0
    assert metrics["prevented_invalid_work_units"] == 0
    assert prediction["repair_attempted_count"] == 0


def test_runtime_stops_at_first_gate(dev_cases):
    case = next(item for item in dev_cases if item["target_rule_id"] == "RCI-C002")
    result = runner.RuntimeResearchCIAdapter().check(BENCHMARK_ROOT / "cases" / case["case_id"])
    assert result.blocked_stage == "pre_run"
    assert list(result.stage_results) == ["pre_run"]


@pytest.mark.parametrize("adapter", [runner.NoCheckAdapter, phase1e.SchemaValidationAdapter, phase1e.ProvenanceOnlyAdapter, phase1e.PosthocResearchCIAdapter, runner.RuntimeResearchCIAdapter])
def test_adapters_do_not_read_hidden_evidence(dev_cases, monkeypatch, adapter):
    original = Path.read_text

    def guarded_read(path, *args, **kwargs):
        assert path.name not in {"ground_truth.json", "ground_truth.jsonl", "mutation.json", "cases.jsonl"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    case = next(item for item in dev_cases if item["target_rule_id"] == "RCI-C005")
    result = adapter().check(BENCHMARK_ROOT / "cases" / case["case_id"])
    assert result.case_id == case["case_id"]


def test_evaluator_reads_truth_only_after_adapter_execution(dev_cases, monkeypatch):
    executed = []
    original = Path.read_text

    class SpyAdapter:
        def check(self, case_dir):
            executed.append(case_dir.name)
            return runner.NoCheckAdapter().check(case_dir)

    def guarded_read(path, *args, **kwargs):
        if path.name == "ground_truth.jsonl":
            assert len(executed) == 120
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    predictions, truth = runner.evaluate_split(BENCHMARK_ROOT, "dev", SpyAdapter())
    assert len(predictions) == len(truth) == 120


def test_per_rule_recall_uses_that_rule_and_per_repo_aggregates():
    assert hasattr(phase1e, "group_metrics"), "缺少逐规则与逐仓库 evaluator"
    truth = [
        {"case_id": "i", "label": "invalid", "expected_rule_ids": ["RCI-C001", "RCI-C002"], "target_stage": "pre_run", "expected_locations": []},
        {"case_id": "v", "label": "valid", "expected_rule_ids": [], "expected_locations": []},
    ]
    predictions = [runner.AdapterResult("i", "toy", "BLOCK", "post_hoc", ["RCI-C001"], [], {}, 0).as_dict(), runner.NoCheckAdapter().check(Path("v")).as_dict()]
    grouped = phase1e.group_metrics(predictions, truth, {"i": "repo_a", "v": "repo_b"})
    assert grouped["per_rule"]["RCI-C001"] == {"case_count": 1, "recall": 1.0, "exact_rule_id_accuracy": 0.0}
    assert grouped["per_rule"]["RCI-C002"]["recall"] == 0.0
    assert grouped["per_repo"]["repo_a"]["invalid_experiment_escape_rate"] == 1.0
    assert grouped["per_repo"]["repo_b"]["false_block_rate"] == 0.0


def test_matrix_defaults_to_dev_and_exposes_common_result_schema():
    assert hasattr(phase1e, "evaluate_matrix"), "缺少默认 dev 的五 adapter evaluator"
    reports = phase1e.evaluate_matrix(BENCHMARK_ROOT)
    assert set(reports) == {"no_check", "schema_validation", "provenance_only", "posthoc_researchci", "runtime_researchci"}
    for report in reports.values():
        assert report["split"] == "dev"
        assert report["metrics"]["case_count"] == 120
        assert set(report["per_repo"]) == {"tabular_sklearn", "text_classification", "vision_pytorch"}
        assert all({"detection_stage", "escaped", "repair_attempted_count", "repair_success_count"} <= set(item) for item in report["predictions"])
    assert reports["posthoc_researchci"]["metrics"]["invalid_experiment_escape_rate"] == 1.0
    assert reports["posthoc_researchci"]["metrics"]["prevented_invalid_work_units"] == 0
    assert reports["posthoc_researchci"]["repair"]["supported"] is False
    assert reports["runtime_researchci"]["repair"]["attempted_auto_repair_count"] == 45


def test_locked_api_requires_explicit_flag_before_reading_holdout(tmp_path):
    with pytest.raises(ValueError, match="explicit"):
        phase1e.run_locked_matrix(tmp_path, tmp_path, "not-a-sha", "not-a-run")


def test_locked_cli_requires_explicit_flag(monkeypatch, tmp_path, capsys):
    from expcontractbench.__main__ import main

    monkeypatch.setattr(sys, "argv", ["expcontractbench", "phase1e-locked", "--root", str(tmp_path), "--repo-root", str(tmp_path), "--evaluator-sha", "not-a-sha", "--run-id", "not-a-run"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "必须显式" in capsys.readouterr().err


def test_prelock_rejects_benchmark_hash_mismatch(tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(phase1e, "_current_rule_blobs", lambda _: {})
    monkeypatch.setattr(phase1e, "_frozen_rule_blobs", lambda _: {})
    with pytest.raises(RuntimeError, match="freeze"):
        phase1e.prelock_check(tmp_path, tmp_path, "not-a-sha")


def test_prelock_rejects_rule_blob_mismatch(tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(phase1e, "tree_hash", lambda _: phase1e.FROZEN_BENCHMARK_HASH)
    monkeypatch.setattr(phase1e, "_current_rule_blobs", lambda _: {"rule.py": "changed"})
    monkeypatch.setattr(phase1e, "_frozen_rule_blobs", lambda _: {"rule.py": "frozen"})
    with pytest.raises(RuntimeError, match="freeze"):
        phase1e.prelock_check(tmp_path, tmp_path, "not-a-sha")


def test_matrix_failure_does_not_publish_partial_reports(tmp_path, monkeypatch):
    assert hasattr(phase1e, "evaluate_dev_matrix"), "缺少 dev 验证与完整矩阵落盘边界"

    def fail_last(self, case_dir):
        raise RuntimeError("第五个 adapter 执行失败")

    monkeypatch.setattr(runner.RuntimeResearchCIAdapter, "check", fail_last)
    with pytest.raises(RuntimeError, match="第五个"):
        phase1e.evaluate_dev_matrix(BENCHMARK_ROOT, output_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_go_gate_requires_measured_reproducibility():
    assert hasattr(phase1e, "go_no_go"), "缺少从冻结报告计算决策的函数"
    report = {
        "metrics": {"violation_recall": 1.0, "false_block_rate": 0.0, "invalid_experiment_escape_rate": 0.0, "rule_id_accuracy": 1.0},
        "per_rule": {f"RCI-C00{i}": {"case_count": 15, "recall": 1.0} for i in range(1, 7)},
        "repair": {"conditional_repair_success_rate": 1.0, "attempted_auto_repair_count": 45},
    }
    result = phase1e.go_no_go(report, reproducibility=0.0)
    assert result["decision"] == "NO-GO"
    assert result["gates"]["reproducibility"] is False
