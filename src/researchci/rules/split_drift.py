"""RCI-C003：仅比较规范 RunIntent 的顶层 split_hash。"""

from __future__ import annotations

from ..models import ExperimentContract, RunIntent, Violation


RULE_ID = "RCI-C003"
STAGE = "pre_run"


def check_split_drift(
    contract: ExperimentContract, baseline: RunIntent, candidate: RunIntent
) -> list[Violation]:
    """需要相同 split 时检查 provenance；修复要求提供匹配数据支撑的 intent。"""

    if not contract.require_same_split or baseline.split_hash == candidate.split_hash:
        return []
    return [
        Violation(
            rule_id=RULE_ID,
            type="split_drift",
            stage=STAGE,
            location="candidate.split_hash",
            message="candidate split hash differs from baseline split hash",
            expected=baseline.split_hash,
            observed=candidate.split_hash,
            repair={
                "operation": "provide_matching_split_intent",
                "path": "candidate_intent",
                "expected_split_hash": baseline.split_hash,
            },
        )
    ]
