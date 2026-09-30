"""RCI-C006：聚合前 declared run 与 RunResult accounting 检查。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..models import AggregateIntent, ExperimentContract, RunResult, Violation


RULE_ID = "RCI-C006"
STAGE = "pre_aggregate"


def _error(
    *, location: str, message: str, expected: Any, observed: Any, repair: dict[str, Any]
) -> Violation:
    return Violation(
        rule_id=RULE_ID,
        type="run_accounting_error",
        stage=STAGE,
        location=location,
        message=message,
        expected=expected,
        observed=observed,
        repair=repair,
    )


def _unknown_ids(values: tuple[str, ...], declared: set[str], location: str) -> list[Violation]:
    unknown = sorted(set(values) - declared)
    return [
        _error(
            location=location,
            message=f"unknown run ID in {location}",
            expected=sorted(declared),
            observed=unknown,
            repair={"operation": "remove_unknown_run_ids", "path": location, "run_ids": unknown},
        )
    ] if unknown else []


def check_failed_runs(contract: ExperimentContract, aggregate: AggregateIntent) -> list[Violation]:
    """返回全部 C006 accounting 违规；不制造或改写 RunResult。"""

    if not contract.failed_runs_must_be_explicit:
        return []

    declared_sequence = aggregate.baseline_run_ids + aggregate.candidate_run_ids
    declared = set(declared_sequence)
    violations: list[Violation] = []
    if len(declared_sequence) != len(declared):
        duplicates = sorted(run_id for run_id, count in Counter(declared_sequence).items() if count > 1)
        violations.append(
            _error(
                location="declared_run_ids",
                message="declared run IDs are duplicated",
                expected="unique declared run IDs",
                observed=duplicates,
                repair={"operation": "resolve_duplicate_run_ids", "path": "declared_run_ids", "run_ids": duplicates},
            )
        )

    result_counts = Counter(result.run_id for result in aggregate.observed_results)
    duplicate_results = sorted(run_id for run_id, count in result_counts.items() if count > 1)
    for run_id in duplicate_results:
        violations.append(
            _error(
                location=f"observed_results.{run_id}",
                message="multiple RunResult records use the same run ID",
                expected="one RunResult per run ID",
                observed=run_id,
                repair={"operation": "resolve_duplicate_run_results", "run_id": run_id},
            )
        )

    violations.extend(_unknown_ids(aggregate.included_run_ids, declared, "included_run_ids"))
    violations.extend(
        _unknown_ids(aggregate.reported_failed_run_ids, declared, "reported_failed_run_ids")
    )

    for location, values in (
        ("included_run_ids", aggregate.included_run_ids),
        ("reported_failed_run_ids", aggregate.reported_failed_run_ids),
    ):
        duplicates = sorted(run_id for run_id, count in Counter(values).items() if count > 1)
        if duplicates:
            violations.append(
                _error(
                    location=location,
                    message=f"run IDs are duplicated in {location}",
                    expected="unique accounting run IDs",
                    observed=duplicates,
                    repair={
                        "operation": "resolve_duplicate_accounting_ids",
                        "path": location,
                        "run_ids": duplicates,
                    },
                )
            )

    included = set(aggregate.included_run_ids)
    reported_failed = set(aggregate.reported_failed_run_ids)
    overlap = sorted(included & reported_failed)
    if overlap:
        violations.append(
            _error(
                location="run_accounting",
                message="a run cannot be both included and reported failed",
                expected="disjoint accounting sets",
                observed=overlap,
                repair={"operation": "resolve_accounting_overlap", "run_ids": overlap},
            )
        )

    results_by_id: dict[str, RunResult] = {}
    expected_role_by_id = {
        **{run_id: contract.baseline_role for run_id in aggregate.baseline_run_ids},
        **{run_id: contract.candidate_role for run_id in aggregate.candidate_run_ids},
    }
    intent_seed_by_id = {
        run.run_id: run.seed
        for run in (*aggregate.baseline_runs, *aggregate.candidate_runs)
        if run.run_id in declared
    }
    for result in aggregate.observed_results:
        results_by_id.setdefault(result.run_id, result)
        if result.run_id not in declared:
            violations.append(
                _error(
                    location=f"observed_results.{result.run_id}",
                    message="observed RunResult is not declared for this comparison",
                    expected=sorted(declared),
                    observed=result.run_id,
                    repair={
                        "operation": "remove_unknown_run_result",
                        "run_id": result.run_id,
                    },
                )
            )
        elif result.role != expected_role_by_id.get(result.run_id):
            violations.append(
                _error(
                    location=f"observed_results.{result.run_id}.role",
                    message="observed RunResult role does not match declared run ownership",
                    expected=expected_role_by_id.get(result.run_id),
                    observed=result.role,
                    repair={
                        "operation": "manual_resolution_required",
                        "path": f"observed_results.{result.run_id}",
                    },
                )
            )
        if (
            result.run_id in intent_seed_by_id
            and result.seed is not None
            and result.seed != intent_seed_by_id[result.run_id]
        ):
            violations.append(
                _error(
                    location=f"observed_results.{result.run_id}.seed",
                    message="RunIntent and RunResult seed identities disagree",
                    expected=intent_seed_by_id[result.run_id],
                    observed=result.seed,
                    repair={
                        "operation": "manual_resolution_required",
                        "path": f"observed_results.{result.run_id}",
                    },
                )
            )

    for run_id in sorted(declared):
        observed = results_by_id.get(run_id)
        if observed is None:
            violations.append(
                _error(
                    location=f"observed_results.{run_id}",
                    message="declared run has no observed RunResult",
                    expected="observed RunResult",
                    observed="missing",
                    repair={"operation": "provide_run_result", "run_id": run_id},
                )
            )
            continue
        if observed.status == "failed":
            if run_id in included:
                violations.append(
                    _error(
                        location="included_run_ids",
                        message="failed run cannot be included in metric aggregation",
                        expected="successful run IDs only",
                        observed=[run_id],
                        repair={"operation": "remove_failed_run", "path": "included_run_ids", "run_id": run_id},
                    )
                )
            if run_id not in reported_failed:
                violations.append(
                    Violation(
                        rule_id=RULE_ID,
                        type="failed_run_omission",
                        stage=STAGE,
                        location="reported_failed_run_ids",
                        message="observed failed run is not explicitly reported",
                        expected="explicit disclosure",
                        observed=[run_id],
                        repair={
                            "operation": "report_failed_run",
                            "path": "reported_failed_run_ids",
                            "run_id": run_id,
                        },
                    )
                )
        else:
            if run_id in reported_failed:
                violations.append(
                    _error(
                        location="reported_failed_run_ids",
                        message="successful run cannot be reported as failed",
                        expected="failed RunResult IDs only",
                        observed=[run_id],
                        repair={"operation": "remove_successful_run", "path": "reported_failed_run_ids", "run_id": run_id},
                    )
                )
            if run_id not in included:
                violations.append(
                    _error(
                        location="included_run_ids",
                        message="successful declared run is omitted from aggregation",
                        expected="explicit inclusion",
                        observed=[run_id],
                        repair={"operation": "include_successful_run", "path": "included_run_ids", "run_id": run_id},
                    )
                )
    return violations
