from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    mutated["pre_run"]["candidate_intent"]["split_hash"] = f"split-drift-{seed}"
    return mutated, {
        "operator": "top_level_split_hash_change",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {},
        "changed_paths": ["pre_run.candidate_intent.split_hash"],
    }
