from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"
PATHS = ("training.max_epochs", "training.max_steps", "evaluation.max_batches")


def _set(config, path, value):
    section, key = path.split(".")
    config[section][key] = value


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    path = PATHS[seed % len(PATHS)]
    current = mutated["pre_run"]["candidate_intent"]["resolved_config"]
    _set(current, path, current[path.split(".")[0]][path.split(".")[1]] + seed + 1)
    return mutated, {
        "operator": "budget_field_change",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"path": path},
        "changed_paths": [f"pre_run.candidate_intent.resolved_config.{path}"],
    }
