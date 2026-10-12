"""Controlled execution authorization ticket 的离线测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TICKET_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_auth_r0.json"
DOC_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_auth_r0.md"
SCOPE_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_auth_r0_scope_audit.json"


def ticket():
    return json.loads(TICKET_PATH.read_text(encoding="utf-8"))


def validate(*, approval, credential, runtime, scope, repository, protocol, consumed=False):
    if not approval or not scope or not repository or not protocol or consumed:
        return "REJECT"
    if runtime != "Linux WSL2 Ubuntu-22.04":
        return "REJECT"
    if not credential:
        return "HOLD"
    return "READY"


def test_valid_ticket_scope_and_status():
    item = ticket()
    assert item["status"] == "NOT_GRANTED"
    assert item["runtime"]["name"] == "Linux WSL2 Ubuntu-22.04"
    assert item["request"] == {"method": "GET", "endpoint": "/models", "max_requests": 1}
    assert item["credential_policy"] == "callback_only"
    assert item["ledger_policy"] == "single_use"


def test_missing_approval_is_rejected():
    assert validate(approval=False, credential=True, runtime="Linux WSL2 Ubuntu-22.04", scope=True, repository=True, protocol=True) == "REJECT"


def test_missing_credential_source_is_hold():
    assert validate(approval=True, credential=False, runtime="Linux WSL2 Ubuntu-22.04", scope=True, repository=True, protocol=True) == "HOLD"


def test_runtime_mismatch_is_rejected():
    assert validate(approval=True, credential=True, runtime="Windows", scope=True, repository=True, protocol=True) == "REJECT"


def test_endpoint_mutation_is_rejected():
    item = ticket()
    assert item["request"]["method"] == "GET"
    assert item["request"]["endpoint"] == "/models"
    assert validate(approval=True, credential=True, runtime="Linux WSL2 Ubuntu-22.04", scope=False, repository=True, protocol=True) == "REJECT"


def test_ticket_replay_is_rejected():
    assert validate(approval=True, credential=True, runtime="Linux WSL2 Ubuntu-22.04", scope=True, repository=True, protocol=True, consumed=True) == "REJECT"
    forbidden = {tuple(item) for item in ticket()["state_machine"]["forbidden_transitions"]}
    assert ("CONSUMED", "READY") in forbidden


def test_binding_fields_are_fixed():
    item = ticket()
    assert item["repository_sha"] == "25e9dfccaaf7cf0113746070db16da3b06efe89a"
    assert item["protocol_hash"].startswith("deepseek=sha256:")
    assert item["binding_requirements"]["scope_fixed"] is True
    assert item["binding_requirements"]["planner_execution_approval"] is False


def test_secret_scan_has_no_material_or_auth_header():
    text = TICKET_PATH.read_text(encoding="utf-8") + "\n" + DOC_PATH.read_text(encoding="utf-8")
    patterns = [r"sk-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}", r"secret\s+value"]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_scope_audit_is_clean_and_counters_zero():
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
    assert scope["execution_authorization"] == "NOT GRANTED"
    item = ticket()
    assert all(value == 0 for value in item["offline_counters"].values())
