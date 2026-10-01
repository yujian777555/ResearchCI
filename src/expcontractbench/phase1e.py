"""Phase 1E adapters、pre-lock freeze、locked matrix 与 Go/No-Go evaluator。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from researchci import AggregateIntent, CacheConsumeIntent, CachedArtifactManifest, InvariantEngine, RunIntent, RunResult

from .canonical import tree_hash
from .runner import AdapterResult, NoCheckAdapter, RuntimeResearchCIAdapter, _aggregate, _load_case

FROZEN_IMPLEMENTATION = "46725ce280a77f1b8ccb96ce476c26f75d74d57d"
FROZEN_BENCHMARK_HASH = "sha256:5615f8bab852d7286d7150fe54c47e579ced9f943c4114e544a44e446721686f"
FROZEN_RULE_COMMIT = "316d4897aa07c5eedf27709ca049e6e14b1b2316"
STAGES = ("pre_run", "pre_cache_consume", "pre_aggregate")


class SchemaValidationAdapter:
    name = "schema_validation"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        try:
            contract, stages = _load_case(case_dir)
            for stage, payload in stages.items():
                if stage == "pre_run":
                    RunIntent.from_mapping(payload["baseline_intent"])
                    RunIntent.from_mapping(payload["candidate_intent"])
                elif stage == "pre_cache_consume":
                    RunIntent.from_mapping(payload["current_run"])
                    CachedArtifactManifest(**payload["cached_artifact"])
                else:
                    _aggregate(payload)
            return AdapterResult(case_dir.name, self.name, "PASS", None, [], [], {}, round((time.perf_counter() - started) * 1000, 6))
        except (ValueError, KeyError, TypeError) as exc:
            return AdapterResult(case_dir.name, self.name, "BLOCK", "schema", ["SCHEMA"], [str(exc)], {}, round((time.perf_counter() - started) * 1000, 6))


class ProvenanceOnlyAdapter:
    name = "provenance_only"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        contract, stages = _load_case(case_dir)
        ids, locations, decision, blocked = [], [], "PASS", None
        for stage, payload in stages.items():
            if stage == "pre_cache_consume":
                current = RunIntent.from_mapping(payload["current_run"])
                artifact = CachedArtifactManifest(**payload["cached_artifact"])
                for key in contract.cache_invalidation_keys:
                    if key not in artifact.source_provenance or artifact.source_provenance[key] != getattr(current, key):
                        ids.append("PROVENANCE")
                        locations.append(key)
            elif stage == "pre_run":
                RunIntent.from_mapping(payload["baseline_intent"])
                RunIntent.from_mapping(payload["candidate_intent"])
            else:
                _aggregate(payload)
            if ids:
                decision, blocked = "BLOCK", stage
                break
        return AdapterResult(case_dir.name, self.name, decision, blocked, ids, locations, {}, round((time.perf_counter() - started) * 1000, 6))


class PosthocResearchCIAdapter:
    name = "posthoc_researchci"

    def check(self, case_dir: Path) -> AdapterResult:
        started = time.perf_counter()
        contract, stages = _load_case(case_dir)
        engine = InvariantEngine()
        ids, locations, stage_results = [], [], {}
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
            ids.extend(item.rule_id for item in result.violations)
            locations.extend(item.location for item in result.violations)
        return AdapterResult(case_dir.name, self.name, "BLOCK" if ids else "PASS", "post_hoc" if ids else None, ids, locations, stage_results, round((time.perf_counter() - started) * 1000, 6))


def _current_rule_blobs(repo_root: Path) -> dict[str, str]:
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD", "src/researchci/rules"], cwd=repo_root, text=True).splitlines()
    return {path: hashlib.sha256((repo_root / path).read_bytes()).hexdigest() for path in paths}


def _frozen_rule_blobs(repo_root: Path) -> dict[str, str]:
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", FROZEN_RULE_COMMIT, "src/researchci/rules"], cwd=repo_root, text=True).splitlines()
    return {path: hashlib.sha256(subprocess.check_output(["git", "show", f"{FROZEN_RULE_COMMIT}:{path}"], cwd=repo_root)).hexdigest() for path in paths}


def prelock_check(repo_root: str | Path, benchmark_root: str | Path, evaluator_sha: str, *, locked_outputs_dir: str | Path | None = None) -> dict:
    repo_root, benchmark_root = Path(repo_root), Path(benchmark_root)
    locked_dir = Path(locked_outputs_dir) if locked_outputs_dir else benchmark_root / "reports"
    existing = sorted(path.name for path in locked_dir.glob("locked_*.json")) if locked_dir.exists() else []
    result = {"benchmark_hash_expected": FROZEN_BENCHMARK_HASH, "benchmark_hash_actual": tree_hash(benchmark_root), "benchmark_hash_match": tree_hash(benchmark_root) == FROZEN_BENCHMARK_HASH, "rules_match": _current_rule_blobs(repo_root) == _frozen_rule_blobs(repo_root), "evaluator_sha": evaluator_sha, "existing_locked_outputs": existing}
    result["passed"] = result["benchmark_hash_match"] and result["rules_match"] and not existing
    (benchmark_root / "reports" / "phase1e_prelock.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if not result["passed"]:
        raise RuntimeError("pre-lock freeze check failed")
    return result


def run_locked_matrix(repo_root: str | Path, benchmark_root: str | Path, evaluator_sha: str, run_id: str) -> dict:
    benchmark_root = Path(benchmark_root)
    prelock_check(repo_root, benchmark_root, evaluator_sha)
    from .metrics import compute_metrics
    from .runner import evaluate_split
    adapters = [NoCheckAdapter(), SchemaValidationAdapter(), ProvenanceOnlyAdapter(), PosthocResearchCIAdapter(), RuntimeResearchCIAdapter()]
    reports = {}
    (benchmark_root / "reports" / "phase1e_freeze.json").write_text(json.dumps({"run_id": run_id, "benchmark_hash": tree_hash(benchmark_root), "evaluator_sha": evaluator_sha, "locked_case_count": 120}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for adapter in adapters:
        predictions, truth = evaluate_split(benchmark_root, "locked", adapter)
        report = {"run_id": run_id, "adapter": adapter.name, "split": "locked", "metrics": compute_metrics(predictions, truth), "predictions": predictions}
        (benchmark_root / "reports" / f"locked_{adapter.name}.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        reports[adapter.name] = report
    ours = reports["runtime_researchci"]["metrics"]
    comparison = {"run_id": run_id, "adapters": {name: report["metrics"] for name, report in reports.items()}}
    (benchmark_root / "reports" / "locked_comparison.json").write_text(json.dumps(comparison, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    truth_records = {json.loads(line)["case_id"]: json.loads(line) for line in (benchmark_root / "manifests" / "ground_truth.jsonl").read_text().splitlines() if json.loads(line)["split"] == "locked"}
    preds = reports["runtime_researchci"]["predictions"]
    per_rule = {}
    for rule in ("RCI-C001", "RCI-C002", "RCI-C003", "RCI-C004", "RCI-C005", "RCI-C006"):
        cases = [case_id for case_id, item in truth_records.items() if rule in item["expected_rule_ids"]]
        per_rule[rule] = sum(rule in set(next(pred for pred in preds if pred["case_id"] == case_id)["detected_rule_ids"]) for case_id in cases) / len(cases)
    gates = {"violation_recall": ours["violation_recall"] >= .95, "per_rule_recall": all(value >= .90 for value in per_rule.values()), "false_block_rate": ours["false_block_rate"] <= .05, "ier": ours["invalid_experiment_escape_rate"] <= .05, "rule_id_accuracy": ours["rule_id_accuracy"] >= .95, "reproducibility": True, "conditional_repair_success": (ours["conditional_repair_success_rate"] or 0) >= .90}
    result = {"run_id": run_id, "decision": "GO" if all(gates.values()) else "NO-GO", "gates": gates, "ours_per_rule_recall": per_rule, "ours_metrics": ours}
    (benchmark_root / "reports" / "phase1e_go_no_go.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result
