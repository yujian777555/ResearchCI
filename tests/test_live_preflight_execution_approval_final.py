"""FINAL-R0 的离线 artifact binding 决策测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_approval_final_r0.json"
DOC = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_approval_final_r0.md"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_approval_final_r0_scope_audit.json"


def artifact():
    return json.loads(DECISION.read_text(encoding="utf-8"))


def decide(*, repository_match, runtime, grant, credential, planner, scope, auth_valid):
    if not repository_match or not scope or not auth_valid:
        return "REJECT"
    if runtime != "Linux WSL2 Ubuntu-22.04" or grant != "GRANTED" or not credential or not planner:
        return "HOLD"
    return "APPROVE"


def test_missing_grant_is_hold():
    assert decide(repository_match=True, runtime="Linux WSL2 Ubuntu-22.04", grant="HOLD", credential=True, planner=True, scope=True, auth_valid=True) == "HOLD"


def test_missing_credential_is_hold():
    assert decide(repository_match=True, runtime="Linux WSL2 Ubuntu-22.04", grant="GRANTED", credential=False, planner=True, scope=True, auth_valid=True) == "HOLD"


def test_scope_mutation_is_rejected():
    assert decide(repository_match=True, runtime="Linux WSL2 Ubuntu-22.04", grant="GRANTED", credential=True, planner=True, scope=False, auth_valid=True) == "REJECT"


def test_artifact_sha_mismatch_is_rejected():
    item = artifact()
    assert item["decision"] == "REJECT"
    assert item["artifact_bindings"]["repository_binding_match"] is False
    assert decide(repository_match=False, runtime="Linux WSL2 Ubuntu-22.04", grant="GRANTED", credential=True, planner=True, scope=True, auth_valid=True) == "REJECT"


def test_all_valid_mocked_state_can_approve_without_execution():
    assert decide(repository_match=True, runtime="Linux WSL2 Ubuntu-22.04", grant="GRANTED", credential=True, planner=True, scope=True, auth_valid=True) == "APPROVE"
    assert artifact()["execution_authorization"] == "NOT GRANTED"


def test_scope_is_fixed_and_reasons_are_recorded():
    item = artifact()
    assert item["scope"] == {"method": "GET", "endpoint": "/models", "max_requests": 1}
    assert len(item["rejection_reasons"]) >= 3


def test_secret_scan_has_no_material_or_auth_header():
    text = DECISION.read_text(encoding="utf-8") + "\n" + DOC.read_text(encoding="utf-8")
    patterns = [r"sk-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}", r"secret\s+value"]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_scope_audit_and_counters_are_clean():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
    assert all(value == 0 for value in artifact()["offline_counters"].values())
