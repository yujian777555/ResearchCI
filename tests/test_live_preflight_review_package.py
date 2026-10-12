"""LIVE-PREFLIGHT-REVIEW-R0 审批包的离线完整性测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_review_r0_approval_package.md"
RISK = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_review_r0_risk_register.json"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_review_r0_scope_audit.json"


def contents():
    return PACKAGE.read_text(encoding="utf-8"), json.loads(RISK.read_text(encoding="utf-8")), json.loads(SCOPE.read_text(encoding="utf-8"))


def test_package_completeness():
    package, risk, scope = contents()
    for phrase in ["Executive Summary", "Security Evidence Summary", "Requested Action", "Explicit Non-Goals", "Execution Preconditions", "Approval Decision", "Current Blockers"]:
        assert phrase in package
    assert len(risk["risks"]) >= 5
    assert scope["status"] == "REVIEW_SCOPE_PASS"


def test_security_evidence_summary_and_blockers_present():
    package, _, _ = contents()
    for phrase in ["Authorization", "Evidence Integrity", "TOCTOU Protection", "Linux：PASS", "Windows：PENDING", "LIVE ACTIVATION BLOCKED"]:
        assert phrase in package


def test_requested_scope_is_single_get_models():
    package, _, _ = contents()
    assert "DeepSeek" in package
    assert "GET /models" in package
    assert "Maximum calls：1" in package
    assert "POST /responses" in package


def test_non_goals_are_explicit():
    package, _, _ = contents()
    for phrase in ["model inference", "agent execution", "tool call", "benchmark", "canary", "research task execution"]:
        assert phrase in package


def test_preconditions_are_complete():
    package, _, _ = contents()
    for phrase in ["Planner Approval exists", "Signed authorization valid", "Repository SHA matches", "Protocol hashes match", "Runtime qualification accepted", "One-use ledger available", "Credential source approved", "Audit sink available", "NO EXECUTION"]:
        assert phrase in package


def test_risk_register_has_required_risks_and_fields():
    _, risk, _ = contents()
    ids = {item["risk_id"] for item in risk["risks"]}
    assert ids == {"R1", "R2", "R3", "R4", "R5"}
    for item in risk["risks"]:
        assert set(item) == {"risk_id", "description", "severity", "mitigation", "status"}
    assert risk["decision_template"]["current_execution_authorization"] == "NOT GRANTED"


def test_scope_allowlist_and_blocker_preservation():
    package, _, scope = contents()
    assert "GET /models" in package
    assert "POST /responses" in package
    assert "LIVE ACTIVATION BLOCKED" in package
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False


def test_no_secret_material_or_auth_header_is_present():
    package = PACKAGE.read_text(encoding="utf-8")
    risk = RISK.read_text(encoding="utf-8")
    combined = package + "\n" + risk
    forbidden_patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        r"eyJ[A-Za-z0-9_-]{20,}",
        r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}",
    ]
    assert all(re.search(pattern, combined, flags=re.IGNORECASE) is None for pattern in forbidden_patterns)
    assert "APPROVE" in package
    assert "Decision: [ APPROVE ] [ REJECT ] [ HOLD ]" in package


def test_current_decision_is_unfilled():
    package, risk, _ = contents()
    assert "当前不填写 APPROVE" in package
    assert risk["decision_template"]["decision"] == "NOT_FILLED"
    assert risk["decision_template"]["current_execution_authorization"] == "NOT GRANTED"
