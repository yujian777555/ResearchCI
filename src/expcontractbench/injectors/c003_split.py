from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    split_hash = f"split-drift-{seed}"
    mutated["pre_run"]["candidate_intent"]["split_hash"] = split_hash
    mutated["pre_cache_consume"]["current_run"]["split_hash"] = split_hash
    if "split_hash" in mutated["contract"]["cache"]["invalidation_keys"]:
        mutated["pre_cache_consume"]["cached_artifact"]["source_provenance"]["split_hash"] = split_hash
    return mutated, {
        "operator": "top_level_split_hash_change",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {},
        "changed_paths": ["pre_run.candidate_intent.split_hash"],
    }
