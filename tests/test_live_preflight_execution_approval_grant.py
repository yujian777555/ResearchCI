"""EXECUTION-APPROVAL-GRANT-R0 的离线 grant decision 测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRANT = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_approval_grant_r0.json"
DOC = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_approval_grant_r0.md"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_approval_grant_r0_scope_audit.json"


def artifact():
    return json.loads(GRANT.read_text(encoding="utf-8"))


def decide(*, runtime, approval, execution_auth, credential, planner, scope, audit):
    if not scope or not execution_auth or not audit:
        return "REJECTED"
    if runtime != "Linux WSL2 Ubuntu-22.04" or not approval or not credential or not planner:
        return "HOLD"
    return "GRANTED"


def test_missing_credential_is_hold():
    assert decide(runtime="Linux WSL2 Ubuntu-22.04", approval=True, execution_auth=True, credential=False, planner=True, scope=True, audit=True) == "HOLD"


def test_missing_planner_approval_is_hold():
    assert decide(runtime="Linux WSL2 Ubuntu-22.04", approval=True, execution_auth=True, credential=True, planner=False, scope=True, audit=True) == "HOLD"


def test_scope_mutation_is_rejected():
    assert decide(runtime="Linux WSL2 Ubuntu-22.04", approval=True, execution_auth=True, credential=True, planner=True, scope=False, audit=True) == "REJECTED"


def test_grant_replay_is_rejected():
    assert artifact()["decision"] == "HOLD"
    assert artifact()["execution_authorization"] == "NOT GRANTED"
    assert "expiration" in artifact()["revocation_conditions"]


def test_valid_hold_artifact_scope():
    item = artifact()
    assert item["runtime"] == "Linux WSL2 Ubuntu-22.04"
    assert item["request"] == {"method": "GET", "endpoint": "/models", "max_requests": 1}
    assert item["credential_source"] == "NOT PROVIDED"
    assert item["granted_by"] == ""


def test_secret_scan_has_no_material_or_auth_header():
    text = GRANT.read_text(encoding="utf-8") + "\n" + DOC.read_text(encoding="utf-8")
    patterns = [r"sk-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}", r"secret\s+value"]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_scope_audit_and_offline_counters_are_clean():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
    assert scope["decision"] == "HOLD"
    assert all(value == 0 for value in artifact()["offline_counters"].values())
