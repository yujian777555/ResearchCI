from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"
def _set(config, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        config = config[part]
    config[parts[-1]] = value


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    path = tuple(mutated["contract"]["comparison"]["equal_budget_fields"])[seed % len(mutated["contract"]["comparison"]["equal_budget_fields"])]
    current = mutated["pre_run"]["candidate_intent"]["resolved_config"]
    value = current
    for part in path.split("."):
        value = value[part]
    _set(current, path, value + seed + 1)
    return mutated, {
        "operator": "budget_field_change",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"path": path},
        "changed_paths": [f"pre_run.candidate_intent.resolved_config.{path}"],
    }
