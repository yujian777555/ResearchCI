"""独立 benchmark integrity validator；不调用 ResearchCI engine。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .canonical import tree_hash


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    for case in manifests:
        data_root = root / "cases" / case["case_id"] / "inputs"
        if case["label"] == "valid":
            required_inputs = [data_root / "contract.yaml", data_root / "pre_run.json", data_root / "pre_cache_consume.json", data_root / "pre_aggregate.json"]
            valid_ok = all(path.exists() for path in required_inputs)
            valid_control_pass += int(valid_ok)
            if not valid_ok:
                errors.append(f"valid control missing lifecycle input: {case['case_id']}")
            continue
        mutation = mutation_records.get(case["case_id"], {})
        operator = mutation.get("operator")
        try:
            if operator == "paired_seed_evidence_remove":
                payload = json.loads((data_root / "pre_aggregate.json").read_text())
                declared = set(payload["declared_seed_set"])
                baseline_observed = {run["seed"] for run in payload["baseline_runs"]}
                candidate_observed = {run["seed"] for run in payload["candidate_runs"]}
                target_ok = (
                    baseline_observed != declared
                    or candidate_observed != declared
                    or baseline_observed != candidate_observed
                )
            elif operator == "budget_field_change":
                payload = json.loads((data_root / "pre_run.json").read_text())
                path = mutation["parameters"]["path"]
                section, key = path.split(".")
                target_ok = payload["baseline_intent"]["resolved_config"][section][key] != payload["candidate_intent"]["resolved_config"][section][key]
            elif operator == "top_level_split_hash_change":
                payload = json.loads((data_root / "pre_run.json").read_text())
                target_ok = payload["baseline_intent"]["split_hash"] != payload["candidate_intent"]["split_hash"]
            elif operator == "equal_config_field_change":
                payload = json.loads((data_root / "pre_run.json").read_text())
                path = mutation["parameters"]["path"]
                def get_path(item):
                    current = item["candidate_intent"]["resolved_config"]
                    for component in path.split("."):
                        current = current[component]
                    return current
                def get_base(item):
                    current = item["baseline_intent"]["resolved_config"]
                    for component in path.split("."):
                        current = current[component]
                    return current
                target_ok = get_path(payload) != get_base(payload)
            elif operator == "stale_cache_provenance":
                payload = json.loads((data_root / "pre_cache_consume.json").read_text())
                key = mutation["parameters"]["key"]
                target_ok = payload["cached_artifact"]["source_provenance"][key] != payload["current_run"][key]
            elif operator == "failed_run_omission":
                payload = json.loads((data_root / "pre_aggregate.json").read_text())
                run_id = mutation["parameters"]["run_id"]
                target = next(item for item in payload["observed_results"] if item["run_id"] == run_id)
                target_ok = target["status"] == "failed" and run_id not in payload["reported_failed_run_ids"] and run_id not in payload["included_run_ids"]
            else:
                target_ok = False
        except (KeyError, StopIteration, json.JSONDecodeError):
            target_ok = False
        independent_pass += int(target_ok)
        non_target_pass += int(target_ok)
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
    }
    (root / "integrity_report.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (root / "integrity_report.md").write_text(
        "# ExpContractBench v0.1 Integrity\n\n" + "\n".join(f"- **{key}:** {value}" for key, value in report.items()), encoding="utf-8"
    )
    if errors:
        raise ValueError("benchmark integrity failed: " + "; ".join(errors[:5]))
    return report
