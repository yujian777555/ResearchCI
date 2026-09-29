"""RCI Phase 1A 的无副作用 invariant engine。"""

from __future__ import annotations

from .models import AggregateIntent, CheckResult, ExperimentContract, RunIntent, Violation
from .rules.budget import check_budget
from .rules.seed_set import check_seed_set


class InvariantEngine:
    """只在请求的生命周期阶段执行对应规则。"""

    @staticmethod
    def _validate_roles(
        contract: ExperimentContract, baseline_intent: RunIntent, candidate_intent: RunIntent
    ) -> list[Violation]:
        violations: list[Violation] = []
        if baseline_intent.role != contract.baseline_role:
            violations.append(
                Violation(
                    rule_id="SCHEMA",
                    type="schema_error",
                    stage="pre_run",
                    location="baseline.role",
                    message="baseline intent role does not match the contract baseline role",
                    expected=contract.baseline_role,
                    observed=baseline_intent.role,
                    repair={
                        "operation": "set",
                        "path": "baseline.role",
                        "value": contract.baseline_role,
                    },
                )
            )
        if candidate_intent.role != contract.candidate_role:
            violations.append(
                Violation(
                    rule_id="SCHEMA",
                    type="schema_error",
                    stage="pre_run",
                    location="candidate.role",
                    message="candidate intent role does not match the contract candidate role",
                    expected=contract.candidate_role,
                    observed=candidate_intent.role,
                    repair={
                        "operation": "set",
                        "path": "candidate.role",
                        "value": contract.candidate_role,
                    },
                )
            )
        return violations

    def check_pre_run(
        self, contract: ExperimentContract, baseline_intent: RunIntent, candidate_intent: RunIntent
    ) -> CheckResult:
        role_violations = self._validate_roles(contract, baseline_intent, candidate_intent)
        if role_violations:
            return CheckResult.from_violations(role_violations)
        return CheckResult.from_violations(check_budget(contract, baseline_intent, candidate_intent))

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
