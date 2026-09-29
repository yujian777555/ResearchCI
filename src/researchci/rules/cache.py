"""RCI-C005：缓存消费前的显式 provenance 一致性检查。"""

from __future__ import annotations

from ..models import CacheConsumeIntent, ExperimentContract, Violation


RULE_ID = "RCI-C005"
STAGE = "pre_cache_consume"


def check_cache_provenance(
    contract: ExperimentContract, intent: CacheConsumeIntent
) -> list[Violation]:
    """只检查契约列出的 invalidation keys，不修改缓存或 provenance。"""

    violations: list[Violation] = []
    current = intent.current_run
    cached = intent.cached_artifact.source_provenance
    for key in contract.cache_invalidation_keys:
        location = f"cached_artifact.source_provenance.{key}"
        expected = getattr(current, key)
        if key not in cached:
            violations.append(
                Violation(
                    rule_id=RULE_ID,
                    type="schema_error",
                    stage=STAGE,
                    location=location,
                    message=f"declared cache provenance key {key} is missing",
                    expected=expected,
                    observed="missing",
                    repair={
                        "operation": "invalidate_and_recompute",
                        "artifact_id": intent.cached_artifact.artifact_id,
                        "mismatched_key": key,
                    },
                )
            )
            continue
        observed = cached[key]
        if expected != observed:
            violations.append(
                Violation(
                    rule_id=RULE_ID,
                    type="stale_cache_reuse",
                    stage=STAGE,
                    location=location,
                    message=f"cached provenance key {key} differs from current run provenance",
                    expected=expected,
                    observed=observed,
                    repair={
                        "operation": "invalidate_and_recompute",
                        "artifact_id": intent.cached_artifact.artifact_id,
                        "mismatched_key": key,
                    },
                )
            )
    return violations
