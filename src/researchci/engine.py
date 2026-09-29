"""RCI Phase 1A 的无副作用 invariant engine。"""

from __future__ import annotations

from .models import AggregateIntent, CheckResult, ExperimentContract, RunIntent
from .rules.budget import check_budget
from .rules.seed_set import check_seed_set


class InvariantEngine:
    """只在请求的生命周期阶段执行对应规则。"""

    def check_pre_run(
        self, contract: ExperimentContract, baseline_intent: RunIntent, candidate_intent: RunIntent
    ) -> CheckResult:
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
