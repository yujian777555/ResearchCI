from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"
def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    paths = tuple(mutated["contract"]["comparison"]["equal_config_fields"])
    path = paths[seed % len(paths)]
    config = mutated["pre_run"]["candidate_intent"]["resolved_config"]
    parts = path.split(".")
    current = config
    for part in parts:
        current = current[part]
    current = config
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] += seed + 1 if isinstance(current[parts[-1]], (int, float)) else "-changed"
    return mutated, {
        "operator": "equal_config_field_change",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"path": path},
        "changed_paths": [f"pre_run.candidate_intent.resolved_config.{path}"],
    }
