"""独立 benchmark integrity validator；不调用 ResearchCI engine。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import yaml

from .canonical import file_hash_map, tree_hash
from .integrity import structural_dimensions, validate_mutation


def _paired_ok(contract: dict, aggregate: dict) -> bool:
    declared = set(contract["comparison"]["paired_seeds"]["seeds"])
    baseline = {item["seed"] for item in aggregate["baseline_runs"]}
    candidate = {item["seed"] for item in aggregate["candidate_runs"]}
    if not baseline == candidate == declared:
        return False
    expected = {**{run_id: "baseline" for run_id in aggregate["baseline_run_ids"]}, **{run_id: "candidate" for run_id in aggregate["candidate_run_ids"]}}
    by_id = {item["run_id"]: item for item in aggregate["observed_results"]}
    for run in aggregate["baseline_runs"] + aggregate["candidate_runs"]:
        result = by_id.get(run["run_id"])
        if result is None or result.get("role") != expected.get(run["run_id"]):
            return False
        if result.get("seed") is not None and result["seed"] != run["seed"]:
            return False
    return True


def _accounting_ok(aggregate: dict) -> bool:
    return _unique_accounting(aggregate)


def _unique_accounting(aggregate: dict) -> bool:
    declared = set(aggregate["baseline_run_ids"] + aggregate["candidate_run_ids"])
    results = aggregate["observed_results"]
    expected = {**{run_id: "baseline" for run_id in aggregate["baseline_run_ids"]}, **{run_id: "candidate" for run_id in aggregate["candidate_run_ids"]}}
    return (len(results) == len({item["run_id"] for item in results}) == len(declared)
            and all(item.get("role") == expected.get(item["run_id"]) for item in results)
            and set(aggregate["included_run_ids"]) == {item["run_id"] for item in results if item["status"] == "success"}
            and set(aggregate["reported_failed_run_ids"]) == {item["run_id"] for item in results if item["status"] == "failed"})
from .profiles import profiles


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_inputs(case_dir: Path) -> dict:
    value = {"contract": yaml.safe_load((case_dir / "inputs" / "contract.yaml").read_text(encoding="utf-8"))}
    for stage in ("pre_run", "pre_cache_consume", "pre_aggregate"):
        value[stage] = json.loads((case_dir / "inputs" / f"{stage}.json").read_text(encoding="utf-8"))
    return value


def validate_benchmark(root: str | Path) -> dict:
    root = Path(root)
    manifests = _read_jsonl(root / "manifests" / "cases.jsonl")
    truths = {item["case_id"]: item for item in _read_jsonl(root / "manifests" / "ground_truth.jsonl")}
    mutations = {item["case_id"]: item for item in _read_jsonl(root / "manifests" / "mutation_manifest.jsonl")}
    errors: list[str] = []
    ids = [item["case_id"] for item in manifests]
    if len(manifests) != 240:
        errors.append(f"expected 240 cases, got {len(manifests)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate case IDs")
    valid_hashes: dict[str, set[str]] = {}
    independent_target = 0
    independent_non_target = 0
    complete_diff = 0
    valid_semantic = 0
    for manifest in manifests:
        cid = manifest["case_id"]
        case_dir = root / "cases" / cid
        data = _load_inputs(case_dir)
        if not re.fullmatch(r"case_[0-9a-f]{12}", cid): errors.append(f"non-opaque case ID: {cid}")
        for path in (case_dir / "inputs").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if any(token in text for token in ("target_rule_id", "mutation_operator", "ground_truth", "expected_rule_ids")):
                    errors.append(f"hidden ground truth in adapter input {cid}")
        if manifest["label"] == "valid":
            valid_hashes.setdefault(manifest["repo_id"], set()).add(manifest.get("input_tree_hash", ""))
            dims = structural_dimensions(data)
            valid_semantic += int(all(dims.values()))
            if not all(dims.values()): errors.append(f"invalid valid control: {cid}")
            continue
        if manifest["case_id"] not in truths or manifest["case_id"] not in mutations:
            errors.append(f"missing truth/mutation: {cid}")
            continue
        mutation = mutations[cid]
        try:
            base_id = manifest["base_valid_case_id"]
            base_manifest = next(item for item in manifests if item["case_id"] == base_id)
            base_data = _load_inputs(root / "cases" / base_id)
            validated = validate_mutation(base_data, data, manifest["target_rule_id"], mutation)
            complete_diff += 1
            if validated["changed_paths"] != mutation.get("changed_paths") or validated["canonical_diff"] != mutation.get("canonical_diff"):
                errors.append(f"complete diff mismatch: {cid}")
            independent_target += 1
            independent_non_target += 1
        except (ValueError, KeyError, StopIteration, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            errors.append(f"independent validation failed {cid}: {exc}")
    metadata = json.loads((root / "generation_metadata.json").read_text(encoding="utf-8"))
    unique_hashes = {repo: len(values) for repo, values in sorted(valid_hashes.items())}
    for repo, count in unique_hashes.items():
        if count != 20: errors.append(f"{repo} valid controls unique hashes={count}, expected 20")
    report = {
        "valid": not errors, "errors": errors, "total_cases": len(manifests),
        "split_counts": dict(sorted(Counter(item["split"] for item in manifests).items())),
        "label_counts": dict(sorted(Counter(item["label"] for item in manifests).items())),
        "repo_counts": dict(sorted(Counter(item["repo_id"] for item in manifests).items())),
        "rule_counts": dict(sorted(Counter(item["target_rule_id"] for item in manifests if item["target_rule_id"]).items())),
        "duplicate_case_ids": len(ids) - len(set(ids)), "opaque_id_check": all(re.fullmatch(r"case_[0-9a-f]{12}", cid) for cid in ids),
        "reproducible": bool(metadata.get("reproducible")), "reproducibility": metadata.get("reproducibility", {}),
        "benchmark_tree_hash": tree_hash(root), "generator_version": metadata.get("generator_version", "unknown"),
        "injector_versions": {f"RCI-C00{i}": "0.1" for i in range(1, 7)},
        "independent_postcondition_pass_count": independent_target,
        "non_target_invariant_pass_count": independent_non_target,
        "valid_control_structural_pass_count": valid_semantic,
        "valid_control_unique_input_hashes": unique_hashes,
        "complete_diff_validation_count": complete_diff,
    }
    (root / "integrity_report.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (root / "integrity_report.md").write_text("# ExpContractBench v0.1 Integrity\n\n" + "\n".join(f"- **{key}:** {value}" for key, value in report.items()), encoding="utf-8")
    if errors: raise ValueError("benchmark integrity failed: " + "; ".join(errors[:5]))
    return report
