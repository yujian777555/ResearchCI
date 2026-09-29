"""ResearchCI Phase 1A 的规范化数据模型。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from numbers import Integral
from typing import Any, Mapping


class ModelValidationError(ValueError):
    """输入无法转换为规范模型时抛出。"""


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelValidationError(f"{field_name} must be a mapping")
    return deepcopy(dict(value))


def _require_seed(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ModelValidationError(f"{field_name} must be an integer seed")
    return int(value)


def _seed_tuple(values: Any, field_name: str, *, required: bool = True) -> tuple[int, ...]:
    if values is None:
        if required:
            raise ModelValidationError(f"{field_name} is required")
        return ()
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set, frozenset)):
        raise ModelValidationError(f"{field_name} must be a sequence of integers")
    result = tuple(sorted({_require_seed(value, field_name) for value in values}))
    if required and not result:
        raise ModelValidationError(f"{field_name} must not be empty")
    if len(result) != len(tuple(values)):
        raise ModelValidationError(f"{field_name} must not contain duplicate seeds")
    return result


def _path_tuple(values: Any, field_name: str, *, required: bool = True) -> tuple[str, ...]:
    if values is None:
        if required:
            raise ModelValidationError(f"{field_name} is required")
        return ()
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ModelValidationError(f"{field_name} must be a sequence of canonical paths")
    paths: list[str] = []
    for value in values:
        path = _require_non_empty_string(value, field_name)
        parts = path.split(".")
        if any(not part or not part.replace("_", "").isalnum() for part in parts):
            raise ModelValidationError(f"{field_name} contains non-canonical path: {path}")
        paths.append(path)
    if len(set(paths)) != len(paths):
        raise ModelValidationError(f"{field_name} must not contain duplicate paths")
    return tuple(paths)


@dataclass
class ExperimentContract:
    """仅承载 v0.1/C001/C002 所需的显式契约语义。"""

    contract_version: str
    experiment_id: str
    task: str
    baseline_role: str
    candidate_role: str
    paired_seeds_required: bool
    paired_seeds: tuple[int, ...]
    equal_fields: tuple[str, ...]
    allowed_to_change: tuple[str, ...]
    require_all_declared_seeds: bool = True
    primary_metric: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ExperimentContract":
        data = _require_mapping(raw, "contract")
        version = str(data.get("contract_version", ""))
        if not version:
            raise ModelValidationError("contract_version is required")

        experiment = data.get("experiment")
        if not isinstance(experiment, Mapping):
            raise ModelValidationError("experiment is required and must be a mapping")
        comparison = data.get("comparison")
        if not isinstance(comparison, Mapping):
            raise ModelValidationError("comparison is required and must be a mapping")
        paired = comparison.get("paired_seeds")
        if not isinstance(paired, Mapping):
            raise ModelValidationError("comparison.paired_seeds is required and must be a mapping")
        required = paired.get("required")
        if not isinstance(required, bool):
            raise ModelValidationError("comparison.paired_seeds.required must be a boolean")

        seeds = _seed_tuple(paired.get("seeds"), "comparison.paired_seeds.seeds", required=required)
        equal_fields = _path_tuple(comparison.get("equal_fields"), "comparison.equal_fields")
        allowed_to_change = _path_tuple(
            comparison.get("allowed_to_change", []), "comparison.allowed_to_change", required=False
        )
        completeness = data.get("completeness", {})
        if completeness is None:
            completeness = {}
        if not isinstance(completeness, Mapping):
            raise ModelValidationError("completeness must be a mapping")
        aggregation = completeness.get("aggregation")
        if not isinstance(aggregation, Mapping):
            raise ModelValidationError("completeness.aggregation is required and must be a mapping")
        require_all = aggregation.get("require_all_declared_seeds")
        if not isinstance(require_all, bool):
            raise ModelValidationError(
                "completeness.aggregation.require_all_declared_seeds is required and must be a boolean"
            )

        metrics = data.get("metrics", {})
        primary_metric = None
        if metrics is not None:
            if not isinstance(metrics, Mapping):
                raise ModelValidationError("metrics must be a mapping")
            primary = metrics.get("primary", {})
            if primary is not None:
                if not isinstance(primary, Mapping):
                    raise ModelValidationError("metrics.primary must be a mapping")
                if "name" in primary:
                    primary_metric = _require_non_empty_string(primary["name"], "metrics.primary.name")

        return cls(
            contract_version=version,
            experiment_id=_require_non_empty_string(experiment.get("id"), "experiment.id"),
            task=_require_non_empty_string(experiment.get("task"), "experiment.task"),
            baseline_role=_require_non_empty_string(comparison.get("baseline"), "comparison.baseline"),
            candidate_role=_require_non_empty_string(comparison.get("candidate"), "comparison.candidate"),
            paired_seeds_required=required,
            paired_seeds=seeds,
            equal_fields=equal_fields,
            allowed_to_change=allowed_to_change,
            require_all_declared_seeds=require_all,
            primary_metric=primary_metric,
        )


@dataclass
class RunIntent:
    """进程启动前解析得到的规范运行意图。"""

    run_id: str
    role: str
    seed: int
    git_commit: str
    config_hash: str
    dataset_hash: str
    split_hash: str
    evaluator_hash: str
    environment_hash: str
    resolved_config: dict[str, Any]

    def __post_init__(self) -> None:
        self.run_id = _require_non_empty_string(self.run_id, "run_id")
        self.role = _require_non_empty_string(self.role, "role")
        self.seed = _require_seed(self.seed, "seed")
        for field_name in (
            "git_commit",
            "config_hash",
            "dataset_hash",
            "split_hash",
            "evaluator_hash",
            "environment_hash",
        ):
            setattr(self, field_name, _require_non_empty_string(getattr(self, field_name), field_name))
        self.resolved_config = _require_mapping(self.resolved_config, "resolved_config")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RunIntent":
        data = _require_mapping(raw, "run_intent")
        required = (
            "run_id",
            "role",
            "seed",
            "git_commit",
            "config_hash",
            "dataset_hash",
            "split_hash",
            "evaluator_hash",
            "environment_hash",
            "resolved_config",
        )
        missing = [key for key in required if key not in data]
        if missing:
            raise ModelValidationError(f"run_intent missing required fields: {', '.join(missing)}")
        return cls(**{key: data[key] for key in required})


@dataclass
class RunResult:
    """运行结果；失败结果仍保留在 lineage 中。"""

    run_id: str
    status: str
    metrics: dict[str, Any]
    artifact_hash: str
    seed: int | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        self.run_id = _require_non_empty_string(self.run_id, "run_id")
        self.status = _require_non_empty_string(self.status, "status")
        self.metrics = _require_mapping(self.metrics, "metrics")
        self.artifact_hash = _require_non_empty_string(self.artifact_hash, "artifact_hash")
        if self.seed is not None:
            self.seed = _require_seed(self.seed, "seed")
        if self.role is not None:
            self.role = _require_non_empty_string(self.role, "role")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RunResult":
        data = _require_mapping(raw, "run_result")
        required = ("run_id", "status", "metrics", "artifact_hash")
        missing = [key for key in required if key not in data]
        if missing:
            raise ModelValidationError(f"run_result missing required fields: {', '.join(missing)}")
        return cls(
            run_id=data["run_id"],
            status=data["status"],
            metrics=data["metrics"],
            artifact_hash=data["artifact_hash"],
            seed=data.get("seed"),
            role=data.get("role"),
        )


@dataclass
class AggregateIntent:
    """聚合前的声明、运行引用和观测 seed 集合。"""

    experiment_id: str
    baseline_run_ids: tuple[str, ...]
    candidate_run_ids: tuple[str, ...]
    declared_seed_set: tuple[int, ...]
    aggregation_metric: str
    baseline_seed_set: tuple[int, ...] | None = None
    candidate_seed_set: tuple[int, ...] | None = None
    baseline_runs: tuple[RunIntent, ...] = field(default_factory=tuple)
    candidate_runs: tuple[RunIntent, ...] = field(default_factory=tuple)
    observed_results: tuple[RunResult, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.experiment_id = _require_non_empty_string(self.experiment_id, "experiment_id")
        self.baseline_run_ids = tuple(
            _require_non_empty_string(value, "baseline_run_ids") for value in self.baseline_run_ids
        )
        self.candidate_run_ids = tuple(
            _require_non_empty_string(value, "candidate_run_ids") for value in self.candidate_run_ids
        )
        self.declared_seed_set = _seed_tuple(self.declared_seed_set, "declared_seed_set")
        self.aggregation_metric = _require_non_empty_string(self.aggregation_metric, "aggregation_metric")
        self.baseline_seed_set = (
            None
            if self.baseline_seed_set is None
            else _seed_tuple(self.baseline_seed_set, "baseline_seed_set")
        )
        self.candidate_seed_set = (
            None
            if self.candidate_seed_set is None
            else _seed_tuple(self.candidate_seed_set, "candidate_seed_set")
        )
        self.baseline_runs = tuple(self.baseline_runs)
        self.candidate_runs = tuple(self.candidate_runs)
        self.observed_results = tuple(self.observed_results)
        if self.baseline_seed_set is None and self.baseline_runs:
            self.baseline_seed_set = _seed_tuple(
                [run.seed for run in self.baseline_runs], "baseline_runs.seed", required=True
            )
        if self.candidate_seed_set is None and self.candidate_runs:
            self.candidate_seed_set = _seed_tuple(
                [run.seed for run in self.candidate_runs], "candidate_runs.seed", required=True
            )
        if self.baseline_seed_set is None and self.observed_results:
            seeds = [
                result.seed
                for result in self.observed_results
                if result.role == "baseline" and result.seed is not None
            ]
            if seeds:
                self.baseline_seed_set = _seed_tuple(seeds, "observed_results.baseline.seed")
        if self.candidate_seed_set is None and self.observed_results:
            seeds = [
                result.seed
                for result in self.observed_results
                if result.role == "candidate" and result.seed is not None
            ]
            if seeds:
                self.candidate_seed_set = _seed_tuple(seeds, "observed_results.candidate.seed")

    def seed_set_for(self, role: str, declared_role: str | None = None) -> tuple[int, ...] | None:
        if role == "baseline":
            explicit = self.baseline_seed_set
            runs = self.baseline_runs
            run_ids = set(self.baseline_run_ids)
        elif role == "candidate":
            explicit = self.candidate_seed_set
            runs = self.candidate_runs
            run_ids = set(self.candidate_run_ids)
        else:
            raise ModelValidationError(f"unsupported aggregate role: {role}")
        if explicit is not None:
            return explicit
        if runs:
            return _seed_tuple([run.seed for run in runs], f"{role}_runs.seed")
        observed = [
            result.seed
            for result in self.observed_results
            if result.seed is not None
            and (result.role == role or (declared_role is not None and result.role == declared_role) or result.run_id in run_ids)
        ]
        return _seed_tuple(observed, f"{role}_observed.seed") if observed else None


@dataclass(frozen=True)
class Violation:
    """可序列化的单条规则违规或显式 schema 错误。"""

    rule_id: str
    type: str
    stage: str
    location: str
    message: str
    expected: Any
    observed: Any
    repair: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "type": self.type,
            "stage": self.stage,
            "location": self.location,
            "message": self.message,
            "expected": deepcopy(self.expected),
            "observed": deepcopy(self.observed),
            "repair": deepcopy(self.repair),
        }


@dataclass(frozen=True)
class CheckResult:
    """规则执行的确定性结果。"""

    decision: str
    violations: tuple[Violation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.decision not in {"PASS", "BLOCK"}:
            raise ModelValidationError("decision must be PASS or BLOCK")
        if self.decision == "PASS" and self.violations:
            raise ModelValidationError("PASS result cannot contain violations")
        if self.decision == "BLOCK" and not self.violations:
            raise ModelValidationError("BLOCK result must contain violations")

    @classmethod
    def from_violations(cls, violations: list[Violation] | tuple[Violation, ...]) -> "CheckResult":
        ordered = tuple(
            sorted(
                violations,
                key=lambda item: (item.rule_id, item.stage, item.location, item.type, item.message),
            )
        )
        return cls("BLOCK" if ordered else "PASS", ordered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "violations": [violation.as_dict() for violation in self.violations],
        }
