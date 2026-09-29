"""RCI-C002：运行前比较契约声明的 equal budget fields。"""

from __future__ import annotations

from typing import Any

from ..models import ExperimentContract, RunIntent, Violation


RULE_ID = "RCI-C002"
STAGE = "pre_run"
_MISSING = object()


def _get_path(mapping: dict[str, Any], path: str) -> Any:
    current: Any = mapping
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return _MISSING
        current = current[component]
    return current


def _schema_error(path: str, observed: Any) -> Violation:
    return Violation(
        rule_id=RULE_ID,
        type="schema_error",
        stage=STAGE,
        location=f"candidate.{path}" if observed == "candidate" else f"baseline.{path}",
        message=f"declared comparison field {path} is missing from {observed} resolved_config",
        expected="resolved value",
        observed="missing",
        repair={
            "operation": "provide",
            "path": f"{observed}.{path}",
            "value": "required",
        },
    )


def check_budget(
    contract: ExperimentContract, baseline: RunIntent, candidate: RunIntent
) -> list[Violation]:
    """比较全部声明字段；allowed_to_change 对差异具有明确豁免作用。"""

    allowed = set(contract.allowed_to_change)
    violations: list[Violation] = []
    for path in contract.equal_fields:
        if path in allowed:
            continue
        baseline_value = _get_path(baseline.resolved_config, path)
        candidate_value = _get_path(candidate.resolved_config, path)
        if baseline_value is _MISSING:
            violations.append(_schema_error(path, "baseline"))
            continue
        if candidate_value is _MISSING:
            violations.append(_schema_error(path, "candidate"))
            continue
        if baseline_value != candidate_value:
            location = f"candidate.{path}"
            violations.append(
                Violation(
                    rule_id=RULE_ID,
                    type="budget_mismatch",
                    stage=STAGE,
                    location=location,
                    message=(
                        f"comparison-sensitive field {path} differs: "
                        f"baseline={baseline_value!r}, candidate={candidate_value!r}"
                    ),
                    expected=baseline_value,
                    observed=candidate_value,
                    repair={"operation": "set", "path": location, "value": baseline_value},
                )
            )
    return violations
