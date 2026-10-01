"""三个结构不同、各有二十个科学输入对照的 controlled profiles。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .canonical import sha256_value


@dataclass(frozen=True)
class Profile:
    repo_id: str
    task: str
    budget_paths: tuple[str, ...]
    config_paths: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    cache_keys: tuple[str, ...]
    fixture_version: str = "0.1-r1"

    def contract(self) -> dict:
        return {
            "contract_version": "0.1",
            "experiment": {"id": f"{self.repo_id}-exp", "task": self.task},
            "comparison": {
                "baseline": "baseline", "candidate": "candidate", "require_same_split": True,
                "paired_seeds": {"required": True, "seeds": [1, 2, 3]},
                "equal_budget_fields": list(self.budget_paths),
                "equal_config_fields": list(self.config_paths),
                "allowed_to_change": list(self.allowed_paths),
            },
            "metrics": {"primary": {"name": "accuracy", "direction": "maximize", "aggregation": "mean"}},
            "completeness": {"failed_runs": {"must_be_explicit": True}, "aggregation": {"require_all_declared_seeds": True}},
            "cache": {"invalidation_keys": list(self.cache_keys)},
        }

    def resolved_config(self, index: int, role: str) -> dict:
        if self.repo_id == "tabular_sklearn":
            return {"training": {"max_iterations": 50 + index * 5, "sample_count": 100 + index * 10}, "evaluation": {"max_folds": 3 + index % 3}, "preprocessing": {"scaler": "standard" if index % 2 == 0 else "minmax"}, "model": {"max_depth": 3 + index % 5, "solver": "lbfgs" if role == "baseline" else "saga"}}
        if self.repo_id == "vision_pytorch":
            return {"training": {"max_epochs": 10 + index, "max_steps": 100 + 10 * index, "batch_size": 16 + index * 2}, "evaluation": {"max_batches": 5 + index}, "augmentation": {"horizontal_flip": bool(index % 2)}, "model": {"encoder": {"width": 32 + 4 * index}, "optimizer": "adam" if role == "baseline" else "sgd"}}
        return {"training": {"token_budget": 1000 + 100 * index, "max_updates": 20 + index}, "evaluation": {"max_calls": 10 + index}, "tokenization": {"lowercase": bool(index % 2), "max_length": 64 + 8 * index}, "classifier": {"regularization": 0.1 + index / 100, "head": "linear" if role == "baseline" else "mlp"}}

    def _run(self, role: str, seed: int, index: int) -> dict:
        config = self.resolved_config(index, role)
        return {"run_id": f"{role}-{seed}", "role": role, "seed": seed, "git_commit": sha256_value([self.repo_id, "code", index]), "config_hash": sha256_value(config), "dataset_hash": sha256_value([self.repo_id, "data", index]), "split_hash": sha256_value([self.repo_id, "split", index]), "evaluator_hash": sha256_value([self.repo_id, "evaluator", index % 4]), "environment_hash": sha256_value([self.repo_id, "environment", index % 3]), "resolved_config": config}

    def base_case(self, valid_index: int) -> dict:
        baseline = [self._run("baseline", seed, valid_index) for seed in (1, 2, 3)]
        candidate = [self._run("candidate", seed, valid_index) for seed in (1, 2, 3)]
        results = [{"run_id": run["run_id"], "role": run["role"], "seed": run["seed"], "status": "success", "metrics": {"accuracy": 0.7 + valid_index / 1000 + run["seed"] / 10000}, "artifact_hash": sha256_value([run["run_id"], run["config_hash"]])} for run in baseline + candidate]
        return deepcopy({
            "contract": self.contract(),
            "pre_run": {"baseline_intent": deepcopy(baseline[0]), "candidate_intent": deepcopy(candidate[0])},
            "pre_cache_consume": {"current_run": deepcopy(candidate[0]), "cached_artifact": {"artifact_id": f"cache-{self.repo_id}-{valid_index}", "artifact_hash": results[3]["artifact_hash"], "source_provenance": {key: candidate[0][key] for key in self.cache_keys}}},
            "pre_aggregate": {"experiment_id": f"{self.repo_id}-exp", "baseline_run_ids": [run["run_id"] for run in baseline], "candidate_run_ids": [run["run_id"] for run in candidate], "declared_seed_set": [1, 2, 3], "aggregation_metric": "accuracy", "baseline_seed_set": [1, 2, 3], "candidate_seed_set": [1, 2, 3], "baseline_runs": baseline, "candidate_runs": candidate, "observed_results": results, "included_run_ids": [item["run_id"] for item in results], "reported_failed_run_ids": []},
        })


def profiles() -> tuple[Profile, ...]:
    return (
        Profile("tabular_sklearn", "tabular_classification", ("training.max_iterations", "training.sample_count", "evaluation.max_folds"), ("preprocessing.scaler", "model.max_depth"), ("model.solver",), ("git_commit", "config_hash", "dataset_hash", "evaluator_hash")),
        Profile("vision_pytorch", "image_classification", ("training.max_epochs", "training.max_steps", "evaluation.max_batches"), ("training.batch_size", "augmentation.horizontal_flip", "model.encoder.width"), ("model.optimizer",), ("git_commit", "config_hash", "dataset_hash", "split_hash", "evaluator_hash", "environment_hash")),
        Profile("text_classification", "text_classification", ("training.token_budget", "training.max_updates", "evaluation.max_calls"), ("tokenization.lowercase", "tokenization.max_length", "classifier.regularization"), ("classifier.head",), ("config_hash", "dataset_hash", "evaluator_hash", "environment_hash")),
    )


def clone_case(case: dict) -> dict:
    return deepcopy(case)
