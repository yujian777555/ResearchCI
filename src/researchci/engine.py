"""RCI Phase 1A 的无副作用 invariant engine。"""

from __future__ import annotations

from .models import AggregateIntent, CheckResult, ExperimentContract, RunIntent, Violation
from .rules.budget import check_budget
from .rules.config_drift import check_config_drift
from .rules.seed_set import check_seed_set
from .rules.split_drift import check_split_drift


class InvariantEngine:
    """只在请求的生命周期阶段执行对应规则。"""

    @staticmethod
    def _validate_roles(
        contract: ExperimentContract, baseline_intent: RunIntent, candidate_intent: RunIntent
    ) -> list[Violation]:
        baseline_matches = baseline_intent.role == contract.baseline_role
        candidate_matches = candidate_intent.role == contract.candidate_role
        if baseline_matches and candidate_matches:
            return []

        exact_swap = (
            contract.baseline_role != contract.candidate_role
            and baseline_intent.role == contract.candidate_role
            and candidate_intent.role == contract.baseline_role
        )
        if exact_swap:
            return [
                Violation(
                    rule_id="SCHEMA",
                    type="schema_error",
                    stage="pre_run",
                    location="comparison.roles",
                    message="baseline and candidate intents appear to be swapped",
                    expected={
                        "baseline": contract.baseline_role,
                        "candidate": contract.candidate_role,
                    },
                    observed={
                        "baseline": baseline_intent.role,
                        "candidate": candidate_intent.role,
                    },
                    repair={
                        "operation": "swap_intents",
                        "paths": ["baseline_intent", "candidate_intent"],
                    },
                )
            ]

        mismatches = []
        if not baseline_matches:
            mismatches.append(
                (
                    "baseline",
                    "baseline_intent",
                    contract.baseline_role,
                    baseline_intent.role,
                )
            )
        if not candidate_matches:
            mismatches.append(
                (
                    "candidate",
                    "candidate_intent",
                    contract.candidate_role,
                    candidate_intent.role,
                )
            )
        operation = "provide_matching_intent" if len(mismatches) == 1 else "manual_resolution_required"
        violations: list[Violation] = []
        for side, intent_path, expected_role, observed_role in mismatches:
            repair = {
                "operation": operation,
                "path": intent_path,
                "expected_role": expected_role,
            }
            violations.append(
                Violation(
                    rule_id="SCHEMA",
                    type="schema_error",
                    stage="pre_run",
                    location=f"{side}.role",
                    message=f"{side} intent role does not match the contract {side} role",
                    expected=expected_role,
                    observed=observed_role,
                    repair=repair,
                )
            )
        return violations

    def check_pre_run(
        self, contract: ExperimentContract, baseline_intent: RunIntent, candidate_intent: RunIntent
    ) -> CheckResult:
        role_violations = self._validate_roles(contract, baseline_intent, candidate_intent)
        if role_violations:
            return CheckResult.from_violations(role_violations)
        violations = [
            *check_budget(contract, baseline_intent, candidate_intent),
            *check_split_drift(contract, baseline_intent, candidate_intent),
            *check_config_drift(contract, baseline_intent, candidate_intent),
        ]
        return CheckResult.from_violations(violations)

    def check_pre_aggregate(
        self, contract: ExperimentContract, aggregate_intent: AggregateIntent
    ) -> CheckResult:
        return CheckResult.from_violations(check_seed_set(contract, aggregate_intent))


def check_pre_run(
    contract: ExperimentContract, baseline_intent: RunIntent, candidate_intent: RunIntent
) -> CheckResult:
    """函数式 pre_run 入口。"""

    return InvariantEngine().check_pre_run(contract, baseline_intent, candidate_intent)


def check_pre_aggregate(contract: ExperimentContract, aggregate_intent: AggregateIntent) -> CheckResult:
    """函数式 pre_aggregate 入口。"""

    return InvariantEngine().check_pre_aggregate(contract, aggregate_intent)
