"""三个 benchmark-owned 的 CPU-friendly controlled repository profiles。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Profile:
    repo_id: str
    task: str
    fixture_version: str = "0.1"

    def contract(self) -> dict[str, Any]:
        return {
            "contract_version": "0.1",
            "experiment": {"id": f"{self.repo_id}-exp", "task": self.task},
            "comparison": {
                "baseline": "baseline",
                "candidate": "candidate",
                "require_same_split": True,
                "paired_seeds": {"required": True, "seeds": [1, 2, 3]},
                "equal_budget_fields": [
                    "training.max_epochs",
                    "training.max_steps",
                    "evaluation.max_batches",
                ],
                "equal_config_fields": ["training.batch_size", "model.encoder.width"],
                "allowed_to_change": ["model.optimizer"],
            },
            "metrics": {"primary": {"name": "accuracy", "direction": "maximize", "aggregation": "mean"}},
            "completeness": {
                "failed_runs": {"must_be_explicit": True},
                "aggregation": {"require_all_declared_seeds": True},
            },
            "cache": {
                "invalidation_keys": ["git_commit", "config_hash", "dataset_hash", "evaluator_hash"]
            },
        }

    def _run(self, role: str, seed: int) -> dict[str, Any]:
        return {
            "run_id": f"{role}-{seed}",
            "role": role,
            "seed": seed,
            "git_commit": "git-a",
            "config_hash": "config-a",
            "dataset_hash": "dataset-a",
            "split_hash": "split-a",
            "evaluator_hash": "evaluator-a",
            "environment_hash": "environment-a",
            "resolved_config": {
                "training": {"max_epochs": 10, "max_steps": 100, "batch_size": 32},
                "evaluation": {"max_batches": 5},
                "model": {"encoder": {"width": 64}, "optimizer": "adam"},
            },
        }

    def base_case(self, valid_index: int) -> dict[str, Any]:
        baseline_runs = [self._run("baseline", seed) for seed in (1, 2, 3)]
        candidate_runs = [self._run("candidate", seed) for seed in (1, 2, 3)]
        results = [
            {
                "run_id": run["run_id"],
                "status": "success",
                "metrics": {"accuracy": 0.8},
                "artifact_hash": f"artifact-{run['run_id']}",
                "seed": run["seed"],
                "role": run["role"],
            }
            for run in baseline_runs + candidate_runs
        ]
        return {
            "profile": self.repo_id,
            "valid_index": valid_index,
            "contract": self.contract(),
            "pre_run": {"baseline_intent": baseline_runs[0], "candidate_intent": candidate_runs[0]},
            "pre_cache_consume": {
                "current_run": candidate_runs[0],
                "cached_artifact": {
                    "artifact_id": "cache-1",
                    "artifact_hash": "artifact-candidate-1",
                    "source_provenance": {
                        "git_commit": "git-a",
                        "config_hash": "config-a",
                        "dataset_hash": "dataset-a",
                        "evaluator_hash": "evaluator-a",
                    },
                },
            },
            "pre_aggregate": {
                "experiment_id": f"{self.repo_id}-exp",
                "baseline_run_ids": [run["run_id"] for run in baseline_runs],
                "candidate_run_ids": [run["run_id"] for run in candidate_runs],
                "declared_seed_set": [1, 2, 3],
                "aggregation_metric": "accuracy",
                "baseline_seed_set": [1, 2, 3],
                "candidate_seed_set": [1, 2, 3],
                "baseline_runs": baseline_runs,
                "candidate_runs": candidate_runs,
                "observed_results": results,
                "included_run_ids": [result["run_id"] for result in results],
                "reported_failed_run_ids": [],
            },
        }


def profiles() -> tuple[Profile, ...]:
    return (
        Profile("tabular_sklearn", "tabular_classification"),
        Profile("vision_pytorch", "image_classification"),
        Profile("text_classification", "text_classification"),
    )


def clone_case(case: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(case)
