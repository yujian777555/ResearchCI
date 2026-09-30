from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"
def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    keys = tuple(mutated["contract"]["cache"]["invalidation_keys"])
    key = keys[seed % len(keys)]
    mutated["pre_cache_consume"]["cached_artifact"]["source_provenance"][key] = f"stale-{seed}-{key}"
    return mutated, {
        "operator": "stale_cache_provenance",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"key": key},
        "changed_paths": [f"pre_cache_consume.cached_artifact.source_provenance.{key}"],
    }
