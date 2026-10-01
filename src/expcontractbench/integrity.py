"""独立科学结构校验与 injector 修改范围；不导入 ResearchCI。"""

from __future__ import annotations

from .canonical import canonical_diff, get_path


RULE_OPERATORS = {
    "RCI-C001": "paired_seed_evidence_remove", "RCI-C002": "budget_field_change",
    "RCI-C003": "top_level_split_hash_change", "RCI-C004": "equal_config_field_change",
    "RCI-C005": "stale_cache_provenance", "RCI-C006": "failed_run_omission",
}
STAGES = {rule: ("pre_aggregate" if rule in {"RCI-C001", "RCI-C006"} else
                 "pre_cache_consume" if rule == "RCI-C005" else "pre_run") for rule in RULE_OPERATORS}
PROVENANCE_KEYS = {"git_commit", "config_hash", "dataset_hash", "split_hash", "evaluator_hash", "environment_hash"}


def _unique(values) -> bool:
    return len(values) == len(set(values))


def _integer_seed(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _run_schema(run: dict) -> bool:
    return (isinstance(run, dict) and isinstance(run["run_id"], str) and bool(run["run_id"])
            and isinstance(run["role"], str) and bool(run["role"])
            and _integer_seed(run["seed"]) and isinstance(run["resolved_config"], dict)
            and all(isinstance(run[key], str) and bool(run[key]) for key in PROVENANCE_KEYS))


def _aggregate_evidence_ok(aggregate: dict, contract: dict | None = None) -> bool:
    comparison = (contract or {}).get("comparison", {"baseline": "baseline", "candidate": "candidate"})
    all_ids = aggregate["baseline_run_ids"] + aggregate["candidate_run_ids"]
    if not all_ids or not _unique(all_ids):
        return False
    results = aggregate["observed_results"]
    if not _unique([item["run_id"] for item in results]) or {item["run_id"] for item in results} != set(all_ids):
        return False
    result_by_id = {item["run_id"]: item for item in results}
    for side in ("baseline", "candidate"):
        ids = aggregate[f"{side}_run_ids"]
        runs = aggregate[f"{side}_runs"]
        run_ids = [item["run_id"] for item in runs]
        if not _unique(run_ids) or set(run_ids) != set(ids):
            return False
        evidence_seeds = set()
        for run in runs:
            if not _run_schema(run) or run["role"] != comparison[side]:
                return False
            result = result_by_id[run["run_id"]]
            if result.get("role") != comparison[side]:
                return False
            if result.get("seed") is not None and result["seed"] != run["seed"]:
                return False
            evidence_seeds.add(run["seed"])
            if result["status"] not in {"success", "failed"} or not isinstance(result["metrics"], dict):
                return False
            artifact = result["artifact_hash"]
            if result["status"] == "success" and (not isinstance(artifact, str) or not artifact):
                return False
            if result["status"] == "failed" and artifact is not None and (not isinstance(artifact, str) or not artifact):
                return False
        explicit = aggregate.get(f"{side}_seed_set")
        if explicit is not None and (not _unique(explicit) or set(explicit) != evidence_seeds):
            return False
    return True


def _paired_ok(contract: dict, aggregate: dict) -> bool:
    if not _aggregate_evidence_ok(aggregate, contract):
        return False
    declared = set(contract["comparison"]["paired_seeds"]["seeds"])
    if set(aggregate["declared_seed_set"]) != declared:
        return False
    return all({run["seed"] for run in aggregate[f"{side}_runs"]} == declared for side in ("baseline", "candidate"))


def _accounting_ok(aggregate: dict, contract: dict | None = None) -> bool:
    if not _aggregate_evidence_ok(aggregate, contract):
        return False
    included, failed = aggregate["included_run_ids"], aggregate["reported_failed_run_ids"]
    if not _unique(included) or not _unique(failed) or set(included) & set(failed):
        return False
    results = aggregate["observed_results"]
    return (set(included) == {item["run_id"] for item in results if item["status"] == "success"}
            and set(failed) == {item["run_id"] for item in results if item["status"] == "failed"})


def _equal_fields(contract: dict, pre_run: dict, name: str) -> bool:
    allowed = set(contract["comparison"].get("allowed_to_change", []))
    return all(path in allowed or
               get_path(pre_run["baseline_intent"]["resolved_config"], path) ==
               get_path(pre_run["candidate_intent"]["resolved_config"], path)
               for path in contract["comparison"][name])


def structural_dimensions(data: dict) -> dict[str, bool]:
    contract = data["contract"]
    comparison = contract["comparison"]
    run, cache, aggregate = data["pre_run"], data["pre_cache_consume"], data["pre_aggregate"]
    role_ok = all(_run_schema(run[f"{side}_intent"]) and run[f"{side}_intent"]["role"] == comparison[side]
                  for side in ("baseline", "candidate"))
    artifact = cache["cached_artifact"]
    schema_ok = (role_ok and _run_schema(cache["current_run"])
                 and isinstance(artifact["source_provenance"], dict)
                 and all(isinstance(artifact[key], str) and bool(artifact[key]) for key in ("artifact_id", "artifact_hash"))
                 and contract["contract_version"] == "0.1"
                 and comparison["paired_seeds"]["required"] is True
                 and contract["completeness"]["failed_runs"]["must_be_explicit"] is True
                 and contract["completeness"]["aggregation"]["require_all_declared_seeds"] is True
                 and _aggregate_evidence_ok(aggregate, contract)
                 and not set(comparison["equal_budget_fields"]) & set(comparison["equal_config_fields"])
                 and _unique(contract["cache"]["invalidation_keys"])
                 and set(contract["cache"]["invalidation_keys"]) <= PROVENANCE_KEYS)
    return {
        "schema": schema_ok,
        "RCI-C001": _paired_ok(contract, aggregate),
        "RCI-C002": _equal_fields(contract, run, "equal_budget_fields"),
        "RCI-C003": not comparison["require_same_split"] or run["baseline_intent"]["split_hash"] == run["candidate_intent"]["split_hash"],
        "RCI-C004": _equal_fields(contract, run, "equal_config_fields"),
        "RCI-C005": all(key in artifact["source_provenance"] and artifact["source_provenance"][key] == cache["current_run"][key]
                         for key in contract["cache"]["invalidation_keys"]),
        "RCI-C006": _accounting_ok(aggregate, contract),
    }


def allowed_footprint(base: dict, rule: str, parameters: dict) -> set[str]:
    """精确路径由预先定义的 injector 语义给出，不能由实际 diff 推断。"""
    comparison = base["contract"]["comparison"]
    if rule in {"RCI-C002", "RCI-C004"}:
        path = parameters["path"]
        fields = comparison["equal_budget_fields" if rule == "RCI-C002" else "equal_config_fields"]
        if path not in fields or path in comparison["allowed_to_change"]:
            raise ValueError("injector path has no declared ownership")
        return {f"pre_run.candidate_intent.resolved_config.{path}"}
    if rule == "RCI-C003":
        return {"pre_run.candidate_intent.split_hash"}
    if rule == "RCI-C005":
        key = parameters["key"]
        if key not in base["contract"]["cache"]["invalidation_keys"]:
            raise ValueError("cache injector key is not declared")
        return {f"pre_cache_consume.cached_artifact.source_provenance.{key}"}
    if rule == "RCI-C001":
        side, run_id = parameters["role"], parameters["removed_run_id"]
        if side not in {"baseline", "candidate"} or run_id not in base["pre_aggregate"][f"{side}_run_ids"]:
            raise ValueError("removed run is not declared for this side")
        return {f"pre_aggregate.{side}_run_ids", f"pre_aggregate.{side}_runs.{run_id}",
                f"pre_aggregate.observed_results.{run_id}", "pre_aggregate.included_run_ids", f"pre_aggregate.{side}_seed_set"}
    if rule == "RCI-C006":
        run_id = parameters["run_id"]
        row = next(item for item in base["pre_aggregate"]["observed_results"] if item["run_id"] == run_id)
        return {f"pre_aggregate.observed_results.{run_id}.status",
                f"pre_aggregate.observed_results.{run_id}.artifact_hash",
                *(f"pre_aggregate.observed_results.{run_id}.metrics.{key}" for key in row["metrics"]),
                "pre_aggregate.included_run_ids", "pre_aggregate.reported_failed_run_ids"}
    raise ValueError("unsupported mutation rule")


def validate_mutation(base: dict, mutated: dict, rule: str, mutation: dict) -> dict:
    if mutation["operator"] != RULE_OPERATORS[rule]:
        raise ValueError("operator and target rule disagree")
    if not all(structural_dimensions(base).values()):
        raise ValueError("mutation base is not independently valid")
    actual_diff = canonical_diff(base, mutated)
    paths = {row["path"] for row in actual_diff}
    allowed = allowed_footprint(base, rule, mutation["parameters"])
    if not paths or not paths <= allowed:
        raise ValueError(f"unexpected mutation footprint: {sorted(paths - allowed)}")
    dimensions = structural_dimensions(mutated)
    if not dimensions["schema"] or dimensions[rule]:
        raise ValueError("target postcondition is absent or has a schema defect")
    if not all(value for dimension, value in dimensions.items() if dimension != rule):
        raise ValueError("non-target scientific invariant failed")
    if rule == "RCI-C006":
        run_id = mutation["parameters"]["run_id"]
        row = next(item for item in mutated["pre_aggregate"]["observed_results"] if item["run_id"] == run_id)
        if row["status"] != "failed" or row["metrics"] != {} or row["artifact_hash"] is not None or run_id in mutated["pre_aggregate"]["reported_failed_run_ids"]:
            raise ValueError("canonical failed-run omission postcondition failed")
    return {"canonical_diff": actual_diff, "changed_paths": [row["path"] for row in actual_diff],
            "allowed_changed_paths": sorted(allowed)}
