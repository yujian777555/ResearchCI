"""FINAL-APPROVAL-R0 的纯离线决策测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_final_approval_r0.json"
DOCUMENT = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_final_approval_r0.md"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_final_approval_r0_scope_audit.json"


def artifact():
    return json.loads(DECISION.read_text(encoding="utf-8"))


def decide(*, runtime, authorization, execution_plan, credential, planner, scope, evidence):
    if not scope or not authorization or not execution_plan or not evidence:
        return "REJECT"
    if runtime != "ACCEPTED" or not credential or not planner:
        return "HOLD"
    return "APPROVE"


def test_valid_hold():
    item = artifact()
    assert item["decision"] == "HOLD"
    assert item["execution_authorization"] == "NOT GRANTED"
    assert item["planner_explicit_approval"] is False


def test_approve_without_credential_is_rejected_or_hold():
    assert decide(runtime="ACCEPTED", authorization=True, execution_plan=True, credential=False, planner=True, scope=True, evidence=True) == "HOLD"


def test_approve_without_runtime_is_rejected():
    assert decide(runtime="PENDING", authorization=True, execution_plan=True, credential=True, planner=True, scope=True, evidence=True) == "HOLD"


def test_scope_mutation_is_rejected():
    assert decide(runtime="ACCEPTED", authorization=True, execution_plan=True, credential=True, planner=True, scope=False, evidence=True) == "REJECT"


def test_request_scope_is_fixed():
    assert artifact()["request"] == {"provider": "DeepSeek", "method": "GET", "endpoint": "/models", "max_requests": 1}
    assert "POST /responses" in artifact()["forbidden_actions"]


def test_evidence_references_are_present():
    refs = artifact()["evidence_reviewed"]
    assert len(refs) >= 5
    assert any("runtime_resolution" in ref for ref in refs)
    assert any("execution_plan" in ref for ref in refs)


def test_secret_scan_has_no_material_or_auth_header():
    text = DECISION.read_text(encoding="utf-8") + "\n" + DOCUMENT.read_text(encoding="utf-8")
    patterns = [r"sk-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}", r"secret\s+value"]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_decision_does_not_grant_execution():
    item = artifact()
    assert item["approved_by"] == ""
    assert item["credential_status"] == "NOT PROVIDED"
    assert item["live_activation"] == "BLOCKED"


def test_scope_audit_is_clean():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
