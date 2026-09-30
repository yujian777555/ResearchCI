from __future__ import annotations

from copy import deepcopy


OPERATOR_VERSION = "0.1"


def inject(case: dict, seed: int) -> tuple[dict, dict]:
    mutated = deepcopy(case)
    aggregate = mutated["pre_aggregate"]
    target = aggregate["observed_results"][seed % len(aggregate["observed_results"])]
    target["status"] = "failed"
    target["artifact_hash"] = None
    target["metrics"] = {}
    aggregate["included_run_ids"] = [
        run_id for run_id in aggregate["included_run_ids"] if run_id != target["run_id"]
    ]
    aggregate["reported_failed_run_ids"] = [
        run_id for run_id in aggregate["reported_failed_run_ids"] if run_id != target["run_id"]
    ]
    return mutated, {
        "operator": "failed_run_omission",
        "operator_version": OPERATOR_VERSION,
        "seed": seed,
        "parameters": {"run_id": target["run_id"]},
        "changed_paths": [
            f"pre_aggregate.observed_results.{target['run_id']}.status",
            "pre_aggregate.included_run_ids",
            "pre_aggregate.reported_failed_run_ids",
        ],
    }
