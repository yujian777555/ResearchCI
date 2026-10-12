"""最终受控 preflight 决策 artifact 的离线测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_authorization_decision_r0.json"
DOC_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_authorization_decision_r0.md"
SCOPE_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_authorization_decision_r0_scope_audit.json"


def decision():
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


def decide(*, runtime_accepted, credential_approved, planner_approved, authorization_valid, scope_fixed, audit_available):
    if not scope_fixed or not authorization_valid:
        return "REJECT"
    if all([runtime_accepted, credential_approved, planner_approved, audit_available]):
        return "APPROVE"
    return "HOLD"


def test_valid_hold_decision():
    artifact = decision()
    assert artifact["decision"] == "HOLD"
    assert artifact["execution_authorization"] == "NOT GRANTED"
    assert artifact["provider_request_performed"] is False


def test_approve_without_credential_is_rejected_or_hold():
    assert decide(runtime_accepted=True, credential_approved=False, planner_approved=True, authorization_valid=True, scope_fixed=True, audit_available=True) == "HOLD"


def test_approve_with_runtime_pending_is_rejected_or_hold():
    assert decide(runtime_accepted=False, credential_approved=True, planner_approved=True, authorization_valid=True, scope_fixed=True, audit_available=True) == "HOLD"


def test_scope_mutation_is_rejected():
    assert decide(runtime_accepted=True, credential_approved=True, planner_approved=True, authorization_valid=True, scope_fixed=False, audit_available=True) == "REJECT"


def test_scope_is_single_get_models():
    scope = decision()["request_scope"]
    assert scope == {"provider": "DeepSeek", "method": "GET", "endpoint": "/models", "max_requests": 1}
    assert "POST /responses" in decision()["non_goals"]


def test_required_blockers_are_preserved():
    artifact = decision()
    assert artifact["runtime_status"] == "WINDOWS_RUNTIME_VALIDATION_PENDING"
    assert artifact["credential_status"] == "NOT_AVAILABLE_AND_NOT_READ"
    assert artifact["approved_by"] == ""
    assert "HOLD" in artifact["risk_summary"]


def test_secret_scan_has_no_material_or_auth_header():
    combined = DECISION_PATH.read_text(encoding="utf-8") + "\n" + DOC_PATH.read_text(encoding="utf-8")
    patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}",
        r"secret\s+value",
    ]
    assert all(re.search(pattern, combined, flags=re.IGNORECASE) is None for pattern in patterns)


def test_offline_counters_are_zero():
    counters = decision()["offline_counters"]
    assert all(value == 0 for value in counters.values())


def test_scope_audit_is_clean():
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
