"""独立 benchmark integrity validator；不调用 ResearchCI engine。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .canonical import canonical_diff, tree_hash
import yaml


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_inputs(case_dir: Path) -> dict:
    value = {"contract": yaml.safe_load((case_dir / "inputs" / "contract.yaml").read_text(encoding="utf-8"))}
    for stage in ("pre_run", "pre_cache_consume", "pre_aggregate"):
        value[stage] = json.loads((case_dir / "inputs" / f"{stage}.json").read_text(encoding="utf-8"))
    return value


def _path_value(config: dict, path: str):
    for part in path.split("."):
        config = config[part]
    return config


def _run_role_ok(pre_run: dict) -> bool:
    return pre_run["baseline_intent"]["role"] == "baseline" and pre_run["candidate_intent"]["role"] == "candidate"


def _budget_ok(contract: dict, pre_run: dict) -> bool:
    return all(_path_value(pre_run["baseline_intent"]["resolved_config"], path) == _path_value(pre_run["candidate_intent"]["resolved_config"], path) for path in contract["comparison"]["equal_budget_fields"])


def _config_ok(contract: dict, pre_run: dict) -> bool:
    allowed = set(contract["comparison"].get("allowed_to_change", []))
    return all(path in allowed or _path_value(pre_run["baseline_intent"]["resolved_config"], path) == _path_value(pre_run["candidate_intent"]["resolved_config"], path) for path in contract["comparison"].get("equal_config_fields", []))


def _split_ok(contract: dict, pre_run: dict) -> bool:
    return not contract["comparison"].get("require_same_split", False) or pre_run["baseline_intent"]["split_hash"] == pre_run["candidate_intent"]["split_hash"]


def _cache_ok(contract: dict, cache: dict) -> bool:
    return all(cache["cached_artifact"]["source_provenance"].get(key) == cache["current_run"][key] for key in contract.get("cache", {}).get("invalidation_keys", []))


def _paired_ok(contract: dict, aggregate: dict) -> bool:
    declared = set(contract["comparison"]["paired_seeds"]["seeds"])
    baseline = {item["seed"] for item in aggregate["baseline_runs"]}
    candidate = {item["seed"] for item in aggregate["candidate_runs"]}
    return baseline == declared and candidate == declared and baseline == candidate


def _accounting_ok(aggregate: dict) -> bool:
    declared = set(aggregate["baseline_run_ids"] + aggregate["candidate_run_ids"])
    results = {item["run_id"]: item for item in aggregate["observed_results"]}
    if set(results) != declared:
        return False
    included = set(aggregate["included_run_ids"])
    failed = set(aggregate["reported_failed_run_ids"])
    if included & failed:
        return False
    for run_id in declared:
        item = results[run_id]
        if item["status"] == "success" and run_id not in included:
            return False
        if item["status"] == "failed" and (run_id in included or run_id not in failed):
            return False
    return True


def _target_postcondition(contract: dict, data: dict, mutation: dict) -> bool:
    op = mutation.get("operator")
    if op == "paired_seed_evidence_remove":
        declared = set(contract["comparison"]["paired_seeds"]["seeds"])
        baseline = {item["seed"] for item in data["pre_aggregate"]["baseline_runs"]}
        candidate = {item["seed"] for item in data["pre_aggregate"]["candidate_runs"]}
        return baseline != declared or candidate != declared or baseline != candidate
    if op == "budget_field_change":
        path = mutation["parameters"]["path"]
        return _path_value(data["pre_run"]["baseline_intent"]["resolved_config"], path) != _path_value(data["pre_run"]["candidate_intent"]["resolved_config"], path)
    if op == "top_level_split_hash_change":
        return data["pre_run"]["baseline_intent"]["split_hash"] != data["pre_run"]["candidate_intent"]["split_hash"]
    if op == "equal_config_field_change":
        path = mutation["parameters"]["path"]
        return _path_value(data["pre_run"]["baseline_intent"]["resolved_config"], path) != _path_value(data["pre_run"]["candidate_intent"]["resolved_config"], path)
    if op == "stale_cache_provenance":
        key = mutation["parameters"]["key"]
        return data["pre_cache_consume"]["cached_artifact"]["source_provenance"][key] != data["pre_cache_consume"]["current_run"][key]
    if op == "failed_run_omission":
        run_id = mutation["parameters"]["run_id"]
        item = next(item for item in data["pre_aggregate"]["observed_results"] if item["run_id"] == run_id)
        return item["status"] == "failed" and run_id not in data["pre_aggregate"]["included_run_ids"] and run_id not in data["pre_aggregate"]["reported_failed_run_ids"]
    return False


def _non_target_ok(contract: dict, data: dict, operator: str) -> bool:
    pre_run = data["pre_run"]
    cache = data["pre_cache_consume"]
    aggregate = data["pre_aggregate"]
    checks = {
        "c001": _run_role_ok(pre_run) and _budget_ok(contract, pre_run) and _config_ok(contract, pre_run) and _split_ok(contract, pre_run) and _cache_ok(contract, cache) and _accounting_ok(aggregate),
        "c002": _run_role_ok(pre_run) and _split_ok(contract, pre_run) and _config_ok(contract, pre_run) and _cache_ok(contract, cache) and _paired_ok(contract, aggregate) and _accounting_ok(aggregate),
        "c003": _run_role_ok(pre_run) and _budget_ok(contract, pre_run) and _config_ok(contract, pre_run) and _cache_ok(contract, cache) and _paired_ok(contract, aggregate) and _accounting_ok(aggregate),
        "c004": _run_role_ok(pre_run) and _budget_ok(contract, pre_run) and _split_ok(contract, pre_run) and _cache_ok(contract, cache) and _paired_ok(contract, aggregate) and _accounting_ok(aggregate),
        "c005": _run_role_ok(pre_run) and _budget_ok(contract, pre_run) and _config_ok(contract, pre_run) and _split_ok(contract, pre_run) and _paired_ok(contract, aggregate) and _accounting_ok(aggregate),
        "c006": _run_role_ok(pre_run) and _budget_ok(contract, pre_run) and _config_ok(contract, pre_run) and _split_ok(contract, pre_run) and _cache_ok(contract, cache) and _paired_ok(contract, aggregate),
    }
    return checks[operator.lower()]


def validate_benchmark(root: str | Path) -> dict:
    root = Path(root)
    manifests = _read_jsonl(root / "manifests" / "cases.jsonl")
    truths = {item["case_id"]: item for item in _read_jsonl(root / "manifests" / "ground_truth.jsonl")}
    errors: list[str] = []
    if len(manifests) != 240:
        errors.append(f"expected 240 cases, got {len(manifests)}")
    ids = [item["case_id"] for item in manifests]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case IDs")
    for case in manifests:
        cid = case["case_id"]
        if not re.fullmatch(r"case_[0-9a-f]{12}", cid):
            errors.append(f"non-opaque case ID: {cid}")
        if cid not in truths:
            errors.append(f"missing ground truth: {cid}")
        if case["label"] == "invalid" and not case.get("target_rule_id"):
            errors.append(f"invalid case without target: {cid}")
        if case["label"] == "valid" and case.get("target_rule_id") is not None:
            errors.append(f"valid case has target: {cid}")
        base = case.get("base_valid_case_id")
        if case["label"] == "invalid" and not any(v["case_id"] == base and v["label"] == "valid" and v["split"] == case["split"] for v in manifests):
            errors.append(f"invalid case base/split mismatch: {cid}")
        input_root = root / "cases" / cid / "inputs"
        for path in input_root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for forbidden in ("target_rule_id", "mutation_operator", "ground_truth", "expected_rule_ids"):
                    if forbidden in text:
                        errors.append(f"hidden ground truth in adapter input {cid}: {forbidden}")
    mutation_records = {item["case_id"]: item for item in _read_jsonl(root / "manifests" / "mutation_manifest.jsonl")}
    independent_pass = 0
    non_target_pass = 0
    valid_control_pass = 0
    complete_diff_pass = 0
    for case in manifests:
        data_root = root / "cases" / case["case_id"] / "inputs"
        data = None
        try:
            data = _load_inputs(root / "cases" / case["case_id"])
        except (OSError, KeyError, yaml.YAMLError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load scientific inputs {case['case_id']}: {exc}")
        if case["label"] == "valid":
            required_inputs = [data_root / "contract.yaml", data_root / "pre_run.json", data_root / "pre_cache_consume.json", data_root / "pre_aggregate.json"]
            valid_ok = all(path.exists() for path in required_inputs) and data is not None
            if valid_ok:
                contract = data["contract"]
                valid_ok = (_run_role_ok(data["pre_run"]) and _budget_ok(contract, data["pre_run"])
                            and _config_ok(contract, data["pre_run"]) and _split_ok(contract, data["pre_run"])
                            and _cache_ok(contract, data["pre_cache_consume"])
                            and _paired_ok(contract, data["pre_aggregate"])
                            and _accounting_ok(data["pre_aggregate"]))
            valid_control_pass += int(valid_ok)
            if not valid_ok:
                errors.append(f"valid control missing lifecycle input: {case['case_id']}")
            continue
        mutation = mutation_records.get(case["case_id"], {})
        operator = mutation.get("operator")
        try:
            target_ok = data is not None and _target_postcondition(data["contract"], data, mutation)
            base_data = _load_inputs(root / "cases" / case["base_valid_case_id"])
            actual_diff = canonical_diff(base_data, data)
            actual_paths = [item["path"] for item in actual_diff]
            manifest_paths = mutation.get("changed_paths", [])
            canonical_paths = [item["path"] for item in mutation.get("canonical_diff", [])]
            diff_ok = actual_paths == manifest_paths == canonical_paths
            if not diff_ok:
                errors.append(f"complete mutation diff mismatch: {case['case_id']}")
            complete_diff_pass += int(diff_ok)
            target_ok = target_ok and diff_ok
            non_target_ok = data is not None and _non_target_ok(
                data["contract"], data, case["target_rule_id"].lower().replace("rci-", "")
            )
        except (KeyError, OSError, StopIteration, json.JSONDecodeError, yaml.YAMLError):
            target_ok = False
            non_target_ok = False
        independent_pass += int(target_ok)
        non_target_pass += int(non_target_ok)
    metadata = json.loads((root / "generation_metadata.json").read_text(encoding="utf-8"))
    report = {
        "valid": not errors,
        "errors": errors,
        "total_cases": len(manifests),
        "split_counts": dict(sorted(Counter(item["split"] for item in manifests).items())),
        "label_counts": dict(sorted(Counter(item["label"] for item in manifests).items())),
        "repo_counts": dict(sorted(Counter(item["repo_id"] for item in manifests).items())),
        "rule_counts": dict(sorted(Counter(item["target_rule_id"] for item in manifests if item["target_rule_id"]).items())),
        "duplicate_case_ids": len(ids) - len(set(ids)),
        "reproducible": bool(metadata["reproducible"]),
        "benchmark_tree_hash": tree_hash(root, excluded_names={"integrity_report.json", "integrity_report.md", "generation_metadata.json"}),
        "generator_version": metadata.get("generator_version", "unknown"),
        "injector_versions": {f"RCI-C00{i}": "0.1" for i in range(1, 7)},
        "opaque_id_check": all(re.fullmatch(r"case_[0-9a-f]{12}", cid) for cid in ids),
        "independent_postcondition_pass_count": independent_pass,
        "non_target_invariant_pass_count": non_target_pass,
        "valid_control_structural_pass_count": valid_control_pass,
        "complete_diff_validation_count": complete_diff_pass,
    }
    (root / "integrity_report.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (root / "integrity_report.md").write_text(
        "# ExpContractBench v0.1 Integrity\n\n" + "\n".join(f"- **{key}:** {value}" for key, value in report.items()), encoding="utf-8"
    )
    if errors:
        raise ValueError("benchmark integrity failed: " + "; ".join(errors[:5]))
    return report
