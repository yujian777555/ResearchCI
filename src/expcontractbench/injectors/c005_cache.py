from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"
KEYS = ("git_commit", "config_hash", "dataset_hash", "evaluator_hash")


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    key = KEYS[seed % len(KEYS)]
    mutated["pre_cache_consume"]["cached_artifact"]["source_provenance"][key] = f"stale-{seed}-{key}"
    return mutated, {
        "operator": "stale_cache_provenance",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"key": key},
        "changed_paths": [f"pre_cache_consume.cached_artifact.source_provenance.{key}"],
    }
