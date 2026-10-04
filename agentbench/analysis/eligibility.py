"""统一的 efficacy eligibility 规则。"""

from __future__ import annotations
from typing import Any


def is_infra_invalid(record: dict[str, Any]) -> bool:
    if record.get("meaningful_model_behavior") is True:
        return False
    if record.get("infra_invalid") is True:
        return True
    return record.get("termination_reason") in {"provider_error", "credential_error", "network_error"} and not record.get("meaningful_model_behavior", False)


def is_efficacy_eligible(record: dict[str, Any]) -> bool:
    return not is_infra_invalid(record)
