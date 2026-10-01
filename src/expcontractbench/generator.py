"""Deterministic ExpContractBench v0.1 generator."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .canonical import canonical_bytes, canonical_diff, file_hash_map, opaque_case_id, sha256_value, tree_hash
from .injectors import INJECTORS
from .profiles import Profile, profiles
from .integrity import validate_mutation


BENCHMARK_VERSION = "0.1"
GENERATOR_VERSION = "0.1-r1"
RULES = tuple(f"RCI-C00{i}" for i in range(1, 7))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _write_case(root: Path, case: dict[str, Any], truth: dict[str, Any], mutation: dict[str, Any]) -> None:
    case_dir = root / "cases" / case["case_id"]
    inputs = case_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "contract.yaml").write_bytes(
        yaml.safe_dump(case["data"]["contract"], sort_keys=True, allow_unicode=True).encode("utf-8")
    )
    for stage in ("pre_run", "pre_cache_consume", "pre_aggregate"):
        if stage in case["data"]:
            _write_json(inputs / f"{stage}.json", case["data"][stage])
    case["input_tree_hash"] = tree_hash(inputs)
    _write_json(case_dir / "case_manifest.json", {key: value for key, value in case.items() if key != "data"})
    _write_json(case_dir / "ground_truth.json", truth)
    _write_json(case_dir / "mutation_manifest.json", mutation)


def _case_record(profile: Profile, split: str, label: str, base_id: str, data: dict, target_rule: str | None, seed: int | None, mutation: dict[str, Any] | None) -> tuple[dict, dict, dict]:
    mutation = mutation or {"operator": "valid_control", "operator_version": "0.1", "seed": None, "parameters": {}, "changed_paths": []}
    case_key = {
        "benchmark_version": BENCHMARK_VERSION,
        "repo_id": profile.repo_id,
        "base_valid_case_id": base_id,
        "mutation": mutation,
        "split": split,
    }
    case_id = base_id if label == "valid" else opaque_case_id(case_key)
    target_stage = {"RCI-C001": "pre_aggregate", "RCI-C002": "pre_run", "RCI-C003": "pre_run", "RCI-C004": "pre_run", "RCI-C005": "pre_cache_consume", "RCI-C006": "pre_aggregate"}.get(target_rule)
    if target_rule == "RCI-C001":
        expected_locations = [
            f"{mutation['parameters']['role']}.seed_set",
            "comparison.paired_seed_set",
        ]
    elif target_rule == "RCI-C002":
        expected_locations = [f"candidate.{mutation['parameters']['path']}"]
    elif target_rule == "RCI-C003":
        expected_locations = ["candidate.split_hash"]
    elif target_rule == "RCI-C004":
        expected_locations = [f"candidate.{mutation['parameters']['path']}"]
    elif target_rule == "RCI-C005":
        expected_locations = [f"cached_artifact.source_provenance.{mutation['parameters']['key']}"]
    elif target_rule == "RCI-C006":
        expected_locations = ["reported_failed_run_ids"]
    else:
        expected_locations = []
    truth = {
        "case_id": case_id,
        "label": label,
        "target_rule_id": target_rule,
        "target_stage": target_stage,
        "expected_decision": "BLOCK" if label == "invalid" else "PASS",
        "expected_rule_ids": [target_rule] if target_rule else [],
        "expected_locations": expected_locations,
        "declared_cost_units": 100 if label == "invalid" else 0,
        "repair_capability": {"RCI-C002": "auto_repairable", "RCI-C004": "auto_repairable", "RCI-C006": "auto_repairable"}.get(target_rule, "requires_reexecution" if target_rule else None),
    }
    case = {
        "benchmark_version": BENCHMARK_VERSION,
        "case_id": case_id,
        "split": split,
        "repo_id": profile.repo_id,
        "repo_fixture_version": profile.fixture_version,
        "base_valid_case_id": base_id,
        "label": label,
        "target_rule_id": target_rule,
        "target_stage": target_stage,
        "expected_decision": truth["expected_decision"],
        "expected_rule_ids": truth["expected_rule_ids"],
        "expected_locations": truth["expected_locations"],
        "mutation": mutation,
        "declared_cost_units": truth["declared_cost_units"],
        "data": data,
    }
    return case, truth, mutation


def generate_benchmark(output: str | Path, *, _verify_reproducibility: bool = True) -> Path:
    root = Path(output).resolve()
    if root.exists() and any(root.iterdir()):
        # 仅允许重建由本生成器管理的目录，拒绝递归删除任意用户目录。
        if not (root / "generation_metadata.json").is_file() or not (root / "manifests/cases.jsonl").is_file():
            raise ValueError("refusing to replace a non-benchmark directory")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "# ExpContractBench v0.1\n\n"
        "This tree is generated deterministically for Phase 1D. The runner defaults to `dev`;\n"
        "the `locked` split is materialized for integrity checks and is not evaluated here.\n\n"
        "Ground truth and mutation manifests are kept separate from adapter inputs.\n",
        encoding="utf-8",
    )
    for profile in profiles():
        profile_root = root / "repos" / profile.repo_id
        profile_root.mkdir(parents=True, exist_ok=True)
        (profile_root / "README.md").write_text(
            f"# Controlled profile: {profile.repo_id}\n\n"
            "This local fixture is deterministic and does not download or train models.\n",
            encoding="utf-8",
        )
        _write_json(
            profile_root / "profile.json",
            {"repo_id": profile.repo_id, "fixture_version": profile.fixture_version, "task": profile.task},
        )
    manifests: list[dict] = []
    truths: list[dict] = []
    mutations: list[dict] = []
    for profile in profiles():
        for valid_index in range(20):
            split = "dev" if valid_index < 10 else "locked"
            base = profile.base_case(valid_index)
            base_case_id = opaque_case_id({"benchmark_version": BENCHMARK_VERSION, "repo_id": profile.repo_id, "valid_index": valid_index, "split": split})
            case, truth, mutation = _case_record(profile, split, "valid", base_case_id, base, None, None, None)
            _write_case(root, case, truth, mutation)
            manifests.append({key: value for key, value in case.items() if key != "data"})
            truths.append(truth)
            mutations.append({"case_id": case["case_id"], **mutation})
        for rule_id in RULES:
            injector = INJECTORS[rule_id]
            for seed in range(10):
                split = "dev" if seed < 5 else "locked"
                valid_index = seed if seed < 5 else 10 + (seed - 5)
                base_id = opaque_case_id({"benchmark_version": BENCHMARK_VERSION, "repo_id": profile.repo_id, "valid_index": valid_index, "split": split})
                base_data = profile.base_case(valid_index)
                mutated, mutation = injector(base_data, seed)
                mutation.update(validate_mutation(base_data, mutated, rule_id, mutation))
                case, truth, mutation = _case_record(profile, split, "invalid", base_id, mutated, rule_id, seed, mutation)
                _write_case(root, case, truth, mutation)
                manifests.append({key: value for key, value in case.items() if key != "data"})
                truths.append(truth)
                mutations.append({"case_id": case["case_id"], **mutation})
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "cases.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in manifests) + "\n",
        encoding="utf-8",
    )
    (manifest_dir / "ground_truth.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in truths) + "\n",
        encoding="utf-8",
    )
    (manifest_dir / "mutation_manifest.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in mutations) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "benchmark_version": BENCHMARK_VERSION,
        "generator_version": GENERATOR_VERSION,
        "case_count": len(manifests),
        "benchmark_tree_hash": tree_hash(root, excluded_names={"integrity_report.json", "integrity_report.md", "generation_metadata.json"}),
        "reproducible": False,
        "reproducibility": {"compared_file_count": 0, "mismatch_count": None, "passed": False},
    }
    _write_json(root / "generation_metadata.json", metadata)
    if _verify_reproducibility:
        evidence = verify_reproducibility(root)
        metadata["reproducible"] = evidence["passed"]
        metadata["reproducibility"] = evidence
        _write_json(root / "generation_metadata.json", metadata)
        if not evidence["passed"]:
            raise ValueError("two-generation reproducibility comparison failed")
    return root


def verify_reproducibility(reference: Path) -> dict:
    """在两个独立临时根生成完整数据，比较每个文件并核对当前 materialized tree。"""
    with tempfile.TemporaryDirectory(prefix="expcontractbench-r1-") as temp_dir:
        first, second = Path(temp_dir) / "first", Path(temp_dir) / "second"
        generate_benchmark(first, _verify_reproducibility=False)
        generate_benchmark(second, _verify_reproducibility=False)
        first_map = file_hash_map(first, deterministic_only=True)
        second_map = file_hash_map(second, deterministic_only=True)
        reference_map = file_hash_map(reference, deterministic_only=True)
        mismatches = sorted(path for path in set(first_map) | set(second_map)
                            if first_map.get(path) != second_map.get(path))
        reference_mismatches = sorted(path for path in set(first_map) | set(reference_map)
                                      if first_map.get(path) != reference_map.get(path))
        return {
            "compared_file_count": len(first_map), "mismatch_count": len(mismatches),
            "reference_mismatch_count": len(reference_mismatches),
            "first_tree_hash": sha256_value(first_map), "second_tree_hash": sha256_value(second_map),
            "reference_tree_hash": sha256_value(reference_map),
            "passed": not mismatches and not reference_mismatches,
        }
