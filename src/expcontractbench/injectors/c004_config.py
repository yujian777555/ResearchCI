from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"
PATHS = ("training.batch_size", "model.encoder.width")


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    path = PATHS[seed % len(PATHS)]
    section, key = path.split(".") if path.count(".") == 1 else ("model.encoder", "width")
    config = mutated["pre_run"]["candidate_intent"]["resolved_config"]
    if path == "training.batch_size":
        config["training"]["batch_size"] += seed + 1
    else:
        config["model"]["encoder"]["width"] += seed + 1
    return mutated, {
        "operator": "equal_config_field_change",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"path": path},
        "changed_paths": [f"pre_run.candidate_intent.resolved_config.{path}"],
    }
