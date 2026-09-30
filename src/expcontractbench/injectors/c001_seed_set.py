from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    aggregate = mutated["pre_aggregate"]
    role = "baseline" if seed % 2 == 0 else "candidate"
    key = f"{role}_run_ids"
    removed_id = aggregate[key].pop(seed % 3)
    run_key = f"{role}_runs"
    aggregate[run_key] = [run for run in aggregate[run_key] if run["run_id"] != removed_id]
    aggregate["observed_results"] = [
        result for result in aggregate["observed_results"] if result["run_id"] != removed_id
    ]
    aggregate["included_run_ids"] = [
        run_id for run_id in aggregate["included_run_ids"] if run_id != removed_id
    ]
    aggregate[f"{role}_seed_set"] = sorted({run["seed"] for run in aggregate[run_key]})
    return mutated, {
        "operator": "paired_seed_evidence_remove",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"role": role, "removed_run_id": removed_id},
        "changed_paths": [f"pre_aggregate.{key}", f"pre_aggregate.{run_key}"],
    }
