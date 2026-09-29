"""RCI-C001：聚合前 paired seed set 完整性检查。"""

from __future__ import annotations

from typing import Any

from ..models import AggregateIntent, ExperimentContract, Violation


RULE_ID = "RCI-C001"
STAGE = "pre_aggregate"


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

    baseline = aggregate.seed_set_for("baseline", contract.baseline_role)
    candidate = aggregate.seed_set_for("candidate", contract.candidate_role)
    violations: list[Violation] = []
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
