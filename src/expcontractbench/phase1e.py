"""Phase 1E 冻结基线、dev 矩阵、唯一 locked 矩阵及 Go/No-Go evaluator。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from researchci import CacheConsumeIntent, CachedArtifactManifest, InvariantEngine, RunIntent

from .canonical import sha256_value, tree_hash
from .runner import AdapterResult, NoCheckAdapter, RuntimeResearchCIAdapter, _aggregate, _load_case, evaluate_split

FROZEN_IMPLEMENTATION = "46725ce280a77f1b8ccb96ce476c26f75d74d57d"
FROZEN_BENCHMARK_HASH = "sha256:5615f8bab852d7286d7150fe54c47e579ced9f943c4114e544a44e446721686f"
FROZEN_RULE_COMMIT = "316d4897aa07c5eedf27709ca049e6e14b1b2316"
RULES = tuple(f"RCI-C00{i}" for i in range(1, 7))
STAGES = ("pre_run", "pre_cache_consume", "pre_aggregate")
LOCKED_CASE_COUNT = 120


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 6)


class SchemaValidationAdapter:
    name = "schema_validation"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        try:
            _contract, stages = _load_case(case_dir)
            for stage, payload in stages.items():
                if stage == "pre_run":
                    RunIntent.from_mapping(payload["baseline_intent"])
                    RunIntent.from_mapping(payload["candidate_intent"])
                elif stage == "pre_cache_consume":
                    RunIntent.from_mapping(payload["current_run"])
                    CachedArtifactManifest(**payload["cached_artifact"])
                else:
                    _aggregate(payload)
            return AdapterResult(case_dir.name, self.name, "PASS", None, [], [], {}, _elapsed(started))
        except (ValueError, KeyError, TypeError) as exc:
            return AdapterResult(case_dir.name, self.name, "BLOCK", "schema", ["SCHEMA"], [str(exc)], {}, _elapsed(started))


class ProvenanceOnlyAdapter:
    name = "provenance_only"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        contract, stages = _load_case(case_dir)
        detected_ids: list[str] = []
        locations: list[str] = []
        blocked_stage = None
        for stage, payload in stages.items():
            if stage == "pre_cache_consume":
                current = RunIntent.from_mapping(payload["current_run"])
                artifact = CachedArtifactManifest(**payload["cached_artifact"])
                for key in contract.cache_invalidation_keys:
                    if key not in artifact.source_provenance or artifact.source_provenance[key] != getattr(current, key):
                        detected_ids.append("RCI-C005")
                        locations.append(key)
            elif stage == "pre_run":
                RunIntent.from_mapping(payload["baseline_intent"])
                RunIntent.from_mapping(payload["candidate_intent"])
            else:
                _aggregate(payload)
            if detected_ids:
                blocked_stage = stage
                break
        return AdapterResult(case_dir.name, self.name, "BLOCK" if detected_ids else "PASS", blocked_stage, detected_ids, locations, {}, _elapsed(started))


class PosthocResearchCIAdapter:
    name = "posthoc_researchci"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        contract, stages = _load_case(case_dir)
        engine = InvariantEngine()
        detected_ids: list[str] = []
        locations: list[str] = []
        stage_results: dict[str, Any] = {}
        for stage in STAGES:
            if stage not in stages:
                continue
            payload = stages[stage]
            if stage == "pre_run":
                result = engine.check_pre_run(contract, RunIntent.from_mapping(payload["baseline_intent"]), RunIntent.from_mapping(payload["candidate_intent"]))
            elif stage == "pre_cache_consume":
                result = engine.check_pre_cache_consume(contract, CacheConsumeIntent(current_run=RunIntent.from_mapping(payload["current_run"]), cached_artifact=CachedArtifactManifest(**payload["cached_artifact"])))
            else:
                result = engine.check_pre_aggregate(contract, _aggregate(payload))
            stage_results[stage] = result.as_dict()
            detected_ids.extend(item.rule_id for item in result.violations)
            locations.extend(item.location for item in result.violations)
        return AdapterResult(case_dir.name, self.name, "BLOCK" if detected_ids else "PASS", "post_hoc" if detected_ids else None, detected_ids, locations, stage_results, _elapsed(started))


def _current_rule_blobs(repo_root: Path) -> dict[str, str]:
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD", "src/researchci/rules"], cwd=repo_root, text=True).splitlines()
    return {path: hashlib.sha256((repo_root / path).read_bytes()).hexdigest() for path in paths}


def _frozen_rule_blobs(repo_root: Path) -> dict[str, str]:
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", FROZEN_RULE_COMMIT, "src/researchci/rules"], cwd=repo_root, text=True).splitlines()
    return {path: hashlib.sha256(subprocess.check_output(["git", "show", f"{FROZEN_RULE_COMMIT}:{path}"], cwd=repo_root)).hexdigest() for path in paths}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluator_source_hashes(repo_root: Path) -> dict[str, str]:
    files = ("src/expcontractbench/phase1e.py", "src/expcontractbench/runner.py", "src/expcontractbench/metrics.py", "src/expcontractbench/__main__.py")
    return {path: _sha256(repo_root / path) for path in files if (repo_root / path).is_file()}


def _manifests_and_repos(benchmark_root: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    manifests = [json.loads(line) for line in (benchmark_root / "manifests" / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return {item["case_id"]: item["repo_id"] for item in manifests}, manifests


def _annotate_predictions(predictions: list[dict[str, Any]], truth: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_order = {"pre_run": 0, "pre_cache_consume": 1, "pre_aggregate": 2}
    truth_by_case = {item["case_id"]: item for item in truth}
    annotated = []
    for prediction in predictions:
        item = dict(prediction)
        expected = truth_by_case[item["case_id"]]
        prevented = expected["label"] == "invalid" and item["runtime_decision"] == "BLOCK" and stage_order.get(item.get("blocked_stage"), 99) <= stage_order.get(expected.get("target_stage"), 99)
        item["escaped"] = expected["label"] == "invalid" and not prevented
        annotated.append(item)
    return annotated


def _group_metrics(predictions: list[dict[str, Any]], groups: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    from .metrics import compute_metrics

    by_case = {item["case_id"]: item for item in predictions}
    return {name: compute_metrics([by_case[item["case_id"]] for item in group], group) for name, group in sorted(groups.items())}


def _per_rule_metrics(predictions: list[dict[str, Any]], truth: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups = {rule: [item for item in truth if item["label"] == "invalid" and rule in set(item.get("expected_rule_ids", []))] for rule in RULES}
    by_case = {item["case_id"]: item for item in predictions}
    result = {}
    for rule, cases in groups.items():
        hits = 0
        exact = 0
        for truth_item in cases:
            predicted = by_case[truth_item["case_id"]]
            expected_ids = set(truth_item.get("expected_rule_ids", []))
            detected_ids = set(predicted.get("detected_rule_ids", []))
            hits += int(rule in detected_ids)
            exact += int(detected_ids == expected_ids)
        result[rule] = {"case_count": len(cases), "recall": hits / len(cases) if cases else 0.0, "exact_rule_id_accuracy": exact / len(cases) if cases else 0.0}
    return result


def _per_repo_metrics(predictions: list[dict[str, Any]], truth: list[dict[str, Any]], repo_by_case: dict[str, str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in truth:
        groups.setdefault(repo_by_case[item["case_id"]], []).append(item)
    return _group_metrics(predictions, groups)


def group_metrics(predictions: list[dict[str, Any]], truth: list[dict[str, Any]], repo_by_case: dict[str, str]) -> dict[str, Any]:
    return {"per_rule": _per_rule_metrics(predictions, truth), "per_repo": _per_repo_metrics(predictions, truth, repo_by_case)}


def _repair_summary(adapter_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    if adapter_name != "runtime_researchci":
        return {"supported": False, "attempted_auto_repair_count": None, "successful_auto_repair_count": None, "conditional_repair_success_rate": None}
    return {"supported": True, "attempted_auto_repair_count": metrics["attempted_auto_repair_count"], "successful_auto_repair_count": metrics["successful_auto_repair_count"], "conditional_repair_success_rate": metrics["conditional_repair_success_rate"]}


def _evaluate_matrix(benchmark_root: Path, split: str) -> dict[str, dict[str, Any]]:
    repo_by_case, manifests = _manifests_and_repos(benchmark_root)
    selected_ids = {item["case_id"] for item in manifests if item["split"] == split}
    adapters = [NoCheckAdapter(), SchemaValidationAdapter(), ProvenanceOnlyAdapter(), PosthocResearchCIAdapter(), RuntimeResearchCIAdapter()]
    reports: dict[str, dict[str, Any]] = {}
    for adapter in adapters:
        predictions, adapter_truth = evaluate_split(benchmark_root, split, adapter)
        if split == "locked" and (len(adapter_truth) != LOCKED_CASE_COUNT or sum(item["label"] == "invalid" for item in adapter_truth) != 90 or sum(item["label"] == "valid" for item in adapter_truth) != 30):
            raise RuntimeError("locked split must contain exactly 90 invalid and 30 valid cases")
        predictions = _annotate_predictions(predictions, adapter_truth)
        from .metrics import compute_metrics

        metrics = compute_metrics(predictions, adapter_truth)
        grouped = group_metrics(predictions, adapter_truth, repo_by_case)
        reports[adapter.name] = {"split": split, "adapter": adapter.name, "metrics": metrics, "per_rule": grouped["per_rule"], "per_repo": grouped["per_repo"], "repair": _repair_summary(adapter.name, metrics), "predictions": predictions}
    return reports


def evaluate_dev_matrix(benchmark_root: str | Path, *, output_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    benchmark_root = Path(benchmark_root)
    reports = _evaluate_matrix(benchmark_root, "dev")
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, report in reports.items():
            (output_dir / f"dev_{name}.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return reports


def evaluate_matrix(benchmark_root: str | Path) -> dict[str, dict[str, Any]]:
    return evaluate_dev_matrix(benchmark_root)


def prelock_check(repo_root: str | Path, benchmark_root: str | Path, evaluator_sha: str, *, locked_outputs_dir: str | Path | None = None) -> dict[str, Any]:
    repo_root, benchmark_root = Path(repo_root), Path(benchmark_root)
    locked_dir = Path(locked_outputs_dir) if locked_outputs_dir else benchmark_root / "reports"
    formal_outputs = {"locked_no_check.json", "locked_schema_validation.json", "locked_provenance_only.json", "locked_posthoc_researchci.json", "locked_runtime_researchci.json", "locked_comparison.json", "locked_comparison.md", "phase1e_freeze.json", "phase1e_go_no_go.json"}
    existing = sorted(path.name for path in locked_dir.iterdir() if path.name in formal_outputs or path.name.startswith(".phase1e_") and path.name.endswith("_staging")) if locked_dir.exists() else []
    actual_rules = _current_rule_blobs(repo_root)
    frozen_rules = _frozen_rule_blobs(repo_root)
    actual_hash = tree_hash(benchmark_root)
    result = {"benchmark_hash_expected": FROZEN_BENCHMARK_HASH, "benchmark_hash_actual": actual_hash, "benchmark_hash_match": actual_hash == FROZEN_BENCHMARK_HASH, "rules_match": actual_rules == frozen_rules, "rule_blob_identity": {"frozen_commit": FROZEN_RULE_COMMIT, "actual_tree": sha256_value(actual_rules), "frozen_tree": sha256_value(frozen_rules), "actual": actual_rules, "frozen": frozen_rules}, "evaluator_sha": evaluator_sha, "evaluator_source_hashes": _evaluator_source_hashes(repo_root), "existing_locked_outputs": existing}
    result["passed"] = result["benchmark_hash_match"] and result["rules_match"] and not existing
    if result["passed"]:
        dev_first = evaluate_dev_matrix(benchmark_root)
        dev_second = evaluate_dev_matrix(benchmark_root)
        dev_a = _semantic_matrix_fingerprint(dev_first)
        dev_b = _semantic_matrix_fingerprint(dev_second)
        result["dev_matrix"] = {"semantic_fingerprint_first": dev_a, "semantic_fingerprint_second": dev_b, "deterministic": dev_a == dev_b}
        result["passed"] = result["passed"] and result["dev_matrix"]["deterministic"]
    else:
        result["dev_matrix"] = {"deterministic": False, "skipped": True}
    (benchmark_root / "reports" / "phase1e_prelock.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if not result["passed"]:
        raise RuntimeError("pre-lock freeze check failed")
    return result


def _locked_output_hashes(report_dir: Path) -> dict[str, str]:
    names = ["locked_no_check.json", "locked_schema_validation.json", "locked_provenance_only.json", "locked_posthoc_researchci.json", "locked_runtime_researchci.json", "locked_comparison.json", "locked_comparison.md"]
    return {name: _sha256(report_dir / name) for name in names if (report_dir / name).exists()}


def _semantic_matrix_fingerprint(reports: dict[str, dict[str, Any]]) -> str:
    normalized = {}
    for name, report in sorted(reports.items()):
        normalized[name] = {"metrics": {key: value for key, value in report["metrics"].items() if key != "runtime_overhead_ms"}, "per_rule": report["per_rule"], "per_repo": {repo: {key: value for key, value in metrics.items() if key != "runtime_overhead_ms"} for repo, metrics in report["per_repo"].items()}, "repair": report["repair"], "predictions": [{key: value for key, value in prediction.items() if key != "elapsed_ms"} for prediction in report["predictions"]]}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def go_no_go(runtime_report: dict[str, Any], *, reproducibility: float) -> dict[str, Any]:
    metrics, per_rule, repair = runtime_report["metrics"], runtime_report["per_rule"], runtime_report["repair"]
    gates = {"violation_recall": metrics["violation_recall"] >= 0.95, "per_rule_recall": all(per_rule[rule]["recall"] >= 0.90 for rule in RULES), "false_block_rate": metrics["false_block_rate"] <= 0.05, "ier": metrics["invalid_experiment_escape_rate"] <= 0.05, "rule_id_accuracy": metrics["rule_id_accuracy"] >= 0.95, "reproducibility": reproducibility >= 1.0, "conditional_repair_success": (repair["conditional_repair_success_rate"] or 0.0) >= 0.90}
    return {"decision": "GO" if all(gates.values()) else "NO-GO", "gates": gates, "ours_metrics": metrics, "ours_per_rule_recall": {rule: per_rule[rule]["recall"] for rule in RULES}, "ours_per_repo": runtime_report.get("per_repo", {})}


def run_locked_matrix(repo_root: str | Path, benchmark_root: str | Path, evaluator_sha: str, run_id: str, *, locked: bool = False) -> dict[str, Any]:
    if not locked:
        raise ValueError("formal locked matrix requires explicit locked=True")
    repo_root, benchmark_root = Path(repo_root), Path(benchmark_root)
    prelock = prelock_check(repo_root, benchmark_root, evaluator_sha)
    reports = _evaluate_matrix(benchmark_root, "locked")
    report_dir = benchmark_root / "reports"
    if len(reports["runtime_researchci"]["predictions"]) != LOCKED_CASE_COUNT:
        raise RuntimeError("locked split size mismatch")
    staging_dir = report_dir / f".phase1e_{run_id}_staging"
    if staging_dir.exists():
        raise RuntimeError("locked staging directory already exists")
    staging_dir.mkdir()
    staged_names = []
    try:
        for name, report in reports.items():
            filename = f"locked_{name}.json"
            (staging_dir / filename).write_text(json.dumps({"run_id": run_id, **report}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            staged_names.append(filename)
        comparison = {"run_id": run_id, "split": "locked", "locked_case_count": LOCKED_CASE_COUNT, "adapters": {name: {"metrics": report["metrics"], "per_rule": report["per_rule"], "per_repo": report["per_repo"], "repair": report["repair"]} for name, report in reports.items()}}
        (staging_dir / "locked_comparison.json").write_text(json.dumps(comparison, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        staged_names.append("locked_comparison.json")
        lines = ["# Phase 1E Locked Comparison", "", f"Run ID: `{run_id}`", "", "| Adapter | IER | Prevention | Recall | Precision | FBR | Rule-ID | Location |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for name, report in reports.items():
            metrics = report["metrics"]
            lines.append(f"| {name} | {metrics['invalid_experiment_escape_rate']:.4f} | {metrics['prevention_rate']:.4f} | {metrics['violation_recall']:.4f} | {metrics['violation_precision']:.4f} | {metrics['false_block_rate']:.4f} | {metrics['rule_id_accuracy']:.4f} | {metrics['location_accuracy']:.4f} |")
        (staging_dir / "locked_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        staged_names.append("locked_comparison.md")
        for filename in staged_names:
            (staging_dir / filename).replace(report_dir / filename)
    except Exception:
        raise
    else:
        staging_dir.rmdir()
    metadata = json.loads((benchmark_root / "generation_metadata.json").read_text(encoding="utf-8"))
    reproducibility_evidence = metadata.get("reproducibility", {})
    measured_reproducibility = 1.0 if metadata.get("reproducible") is True and reproducibility_evidence.get("passed") is True and reproducibility_evidence.get("mismatch_count") == 0 and reproducibility_evidence.get("reference_mismatch_count") == 0 else 0.0
    decision = go_no_go(reports["runtime_researchci"], reproducibility=measured_reproducibility)
    result = {"run_id": run_id, **decision, "output_hash_scope": "locked_adapter_reports+comparison_json+comparison_markdown", "output_hashes": _locked_output_hashes(report_dir)}
    (report_dir / "phase1e_go_no_go.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result["go_no_go_sha256"] = _sha256(report_dir / "phase1e_go_no_go.json")
    freeze = {"benchmark_version": "0.1", "generator_version": "0.1-r1", "benchmark_tree_hash": tree_hash(benchmark_root), "accepted_phase1d_r1_implementation_sha": FROZEN_IMPLEMENTATION, "evaluator_sha": evaluator_sha, "evaluator_source_hashes": prelock["evaluator_source_hashes"], "rule_blob_identity": prelock["rule_blob_identity"], "locked_case_count": LOCKED_CASE_COUNT, "locked_label_counts": {"invalid": 90, "valid": 30}, "run_id": run_id, "reproducibility_evidence": reproducibility_evidence, "output_hash_scope": "locked_adapter_reports+comparison_json+comparison_markdown", "output_hashes": _locked_output_hashes(report_dir), "go_no_go_sha256": result["go_no_go_sha256"]}
    (report_dir / "phase1e_freeze.json").write_text(json.dumps(freeze, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result
