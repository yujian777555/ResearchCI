"""FINAL-READINESS-R1 的离线绑定与阻断测试。"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_final_readiness_r1.json"
REBIND = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_binding_reissue_r0.json"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_final_readiness_r1_scope_audit.json"


def report():
    return json.loads(READINESS.read_text(encoding="utf-8"))


def rebind():
    return json.loads(REBIND.read_text(encoding="utf-8"))


EXPECTED_SCOPE = {"provider": "DeepSeek", "method": "GET", "endpoint": "/models", "max_requests": 1}


def evaluate(item):
    if not item["binding"]["all_bound_to_repository_sha"]:
        return "REJECT"
    if item["scope"] != EXPECTED_SCOPE:
        return "REJECT"
    if item["grant"]["status"] != "GRANTED" or item["credential"]["status"] != "APPROVED":
        return "BLOCKED"
    return "READY_FOR_EXECUTION"


def test_binding_valid():
    item = report()
    chain = rebind()
    assert item["repository_sha"] == "1fa9b1958993c9a89c6001036ead6fdb88064c28"
    assert item["binding"]["all_bound_to_repository_sha"] is True
    assert chain["repository"]["sha"] == item["repository_sha"]
    assert all(chain[key]["repository_sha"] == item["repository_sha"] for key in ["execution_config", "execution_auth", "grant", "approval"])
    assert evaluate(item) == "BLOCKED"


def test_old_sha_is_rejected():
    item = report()
    item["binding"]["all_bound_to_repository_sha"] = False
    assert evaluate(item) == "REJECT"


def test_grant_hold_blocks():
    item = report()
    assert item["grant"]["status"] == "HOLD"
    assert evaluate(item) == "BLOCKED"


def test_missing_credential_blocks():
    item = report()
    assert item["credential"]["status"] == "NOT_PROVIDED"
    assert evaluate(item) == "BLOCKED"


def test_scope_mutation_is_rejected():
    item = report()
    item["scope"]["method"] = "POST"
    item["scope"]["endpoint"] = "/responses"
    assert evaluate(item) == "REJECT"


def test_repository_sha_mismatch_is_rejected():
    item = report()
    item["repository_sha"] = "old-sha"
    item["binding"]["all_bound_to_repository_sha"] = False
    assert evaluate(item) == "REJECT"


def test_blocker_and_scope_audit_are_preserved():
    item = report()
    assert item["execution_authorization"] == "NOT GRANTED"
    assert item["live_activation"] == "BLOCKED"
    assert len(item["blockers"]) >= 3
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False


def test_offline_counters_are_zero():
    assert all(value == 0 for value in report()["offline_counters"].values())


def test_all_valid_mocked_state_is_ready_without_execution():
    item = report()
    item["grant"]["status"] = "GRANTED"
    item["credential"]["status"] = "APPROVED"
    assert evaluate(item) == "READY_FOR_EXECUTION"
    assert all(value == 0 for value in item["offline_counters"].values())
