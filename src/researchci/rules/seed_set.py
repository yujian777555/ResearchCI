"""RCI-C001：聚合前 paired seed set 完整性检查。"""

from __future__ import annotations

from typing import Any

from ..models import AggregateIntent, ExperimentContract, RunIntent, RunResult, Violation


RULE_ID = "RCI-C001"
STAGE = "pre_aggregate"


def _evidence_seed_set(
    contract: ExperimentContract, aggregate: AggregateIntent, role: str
) -> tuple[tuple[int, ...] | None, list[Violation]]:
    """从声明 run evidence 推导 seed；显式 seed set 只在外层做交叉核对。"""

    if role == "baseline":
        declared_ids = set(aggregate.baseline_run_ids)
        run_intents: tuple[RunIntent, ...] = aggregate.baseline_runs
        expected_role = contract.baseline_role
    else:
        declared_ids = set(aggregate.candidate_run_ids)
        run_intents = aggregate.candidate_runs
        expected_role = contract.candidate_role

    evidence: list[RunIntent | RunResult]
    if run_intents:
        evidence = list(run_intents)
    else:
        evidence = [
            result
            for result in aggregate.observed_results
            if result.run_id in declared_ids
        ]

    seeds: set[int] = set()
    for item in evidence:
        if item.run_id not in declared_ids:
            continue
        # Observed RunResult role is checked by C006; do not infer ownership from ID text.
        if isinstance(item, RunResult) and item.role != expected_role:
            continue
        if isinstance(item, RunIntent) and item.role != expected_role:
            return None, [
                _schema_error(
                    f"{role}_runs.{item.run_id}.role",
                    expected_role,
                    item.role,
                    f"{role} run intent role does not match the contract role",
                )
            ]
        if item.seed is None:
            return None, [
                _schema_error(
                    f"observed_results.{item.run_id}.seed",
                    "seed evidence",
                    None,
                    "declared run evidence must carry a seed",
                )
            ]
        seeds.add(item.seed)
    return (tuple(sorted(seeds)) if seeds else None), []


def _schema_error(location: str, expected: Any, observed: Any, message: str) -> Violation:
    return Violation(
        rule_id=RULE_ID,
        type="schema_error",
        stage=STAGE,
        location=location,
        message=message,
        expected=expected,
        observed=observed,
        repair={"operation": "provide", "path": location, "value": expected},
    )


def check_seed_set(contract: ExperimentContract, aggregate: AggregateIntent) -> list[Violation]:
    """返回全部 C001 违规，且不修改输入。"""

    if not contract.paired_seeds_required or not contract.require_all_declared_seeds:
        return []

    declared = set(contract.paired_seeds)
    if set(aggregate.declared_seed_set) != declared:
        return [
            _schema_error(
                "aggregation.declared_seed_set",
                sorted(declared),
                sorted(aggregate.declared_seed_set),
                "aggregate declaration does not match the contract paired seed set",
            )
        ]

    evidence_violations: list[Violation] = []
    if contract.failed_runs_must_be_explicit:
        baseline, baseline_errors = _evidence_seed_set(contract, aggregate, "baseline")
        candidate, candidate_errors = _evidence_seed_set(contract, aggregate, "candidate")
        evidence_violations.extend(baseline_errors)
        evidence_violations.extend(candidate_errors)
        for role, evidence_set, explicit_set in (
            ("baseline", baseline, aggregate.baseline_seed_set),
            ("candidate", candidate, aggregate.candidate_seed_set),
        ):
            if evidence_set is not None and explicit_set is not None and set(evidence_set) != set(explicit_set):
                evidence_violations.append(
                    _schema_error(
                        f"{role}.seed_set",
                        list(evidence_set),
                        list(explicit_set),
                        "legacy seed declaration disagrees with evidence-derived seed set",
                    )
                )
    else:
        baseline = aggregate.seed_set_for("baseline", contract.baseline_role)
        candidate = aggregate.seed_set_for("candidate", contract.candidate_role)
    violations: list[Violation] = []
    violations.extend(evidence_violations)
    if baseline is None:
        violations.append(
            _schema_error(
                "baseline.seed_set", sorted(declared), None, "baseline observed seed set is required"
            )
        )
    if candidate is None:
        violations.append(
            _schema_error(
                "candidate.seed_set", sorted(declared), None, "candidate observed seed set is required"
            )
        )
    if baseline is None or candidate is None:
        return violations

    baseline_set = set(baseline)
    candidate_set = set(candidate)
    for role, observed in (("baseline", baseline_set), ("candidate", candidate_set)):
        missing = sorted(declared - observed)
        if missing:
            location = f"{role}.seed_set"
            violations.append(
                Violation(
                    rule_id=RULE_ID,
                    type="seed_set_mismatch",
                    stage=STAGE,
                    location=location,
                    message=f"{role} is missing declared seeds: {missing}",
                    expected=sorted(declared),
                    observed=sorted(observed),
                    repair={"operation": "add", "path": location, "seeds": missing},
                )
            )
        extra = sorted(observed - declared)
        if extra:
            location = f"{role}.seed_set"
            violations.append(
                Violation(
                    rule_id=RULE_ID,
                    type="seed_set_mismatch",
                    stage=STAGE,
                    location=location,
                    message=f"{role} contains undeclared seeds: {extra}",
                    expected=sorted(declared),
                    observed=sorted(observed),
                    repair={"operation": "remove", "path": location, "seeds": extra},
                )
            )

    if baseline_set != candidate_set:
        violations.append(
            Violation(
                rule_id=RULE_ID,
                type="seed_set_mismatch",
                stage=STAGE,
                location="comparison.paired_seed_set",
                message="baseline and candidate observed seed sets differ",
                expected=sorted(baseline_set),
                observed=sorted(candidate_set),
                repair={
                    "operation": "align",
                    "path": "candidate.seed_set",
                    "value": sorted(baseline_set),
                },
            )
        )
    return violations
