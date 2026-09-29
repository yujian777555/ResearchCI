"""RCI-C004：只比较契约声明的 equal_config_fields。"""

from __future__ import annotations

from typing import Any

from ..models import ExperimentContract, RunIntent, Violation


RULE_ID = "RCI-C004"
STAGE = "pre_run"
_MISSING = object()


def _get_path(config: dict[str, Any], path: str) -> Any:
    current: Any = config
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            return _MISSING
        current = current[component]
    return current


def _missing_path(role: str, path: str) -> Violation:
    location = f"{role}.{path}"
    return Violation(
        rule_id=RULE_ID,
        type="schema_error",
        stage=STAGE,
        location=location,
        message=f"declared equal config field {path} is missing from {role} resolved_config",
        expected="resolved value",
        observed="missing",
        repair={"operation": "provide", "path": location, "value": "required"},
    )


def check_config_drift(
    contract: ExperimentContract, baseline: RunIntent, candidate: RunIntent
) -> list[Violation]:
    """检查显式声明且未获豁免的配置路径，返回全部差异。"""

    allowed = set(contract.allowed_to_change)
    violations: list[Violation] = []
    for path in contract.equal_config_fields:
        if path in allowed:
            continue
        baseline_value = _get_path(baseline.resolved_config, path)
        candidate_value = _get_path(candidate.resolved_config, path)
        if baseline_value is _MISSING:
            violations.append(_missing_path("baseline", path))
        if candidate_value is _MISSING:
            violations.append(_missing_path("candidate", path))
        if baseline_value is _MISSING or candidate_value is _MISSING:
            continue
        if baseline_value != candidate_value:
            location = f"candidate.{path}"
            violations.append(
                Violation(
                    rule_id=RULE_ID,
                    type="unauthorized_config_drift",
                    stage=STAGE,
                    location=location,
                    message=f"declared equal config field {path} differs between baseline and candidate",
                    expected=baseline_value,
                    observed=candidate_value,
                    repair={"operation": "set", "path": location, "value": baseline_value},
                )
            )
    return violations
