"""BINDING-REISSUE-R0 的离线 SHA 与 scope 一致性测试。"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_binding_reissue_r0.json"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_binding_reissue_r0_scope_audit.json"


def report():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def validate_chain(item):
    sha = item["repository"]["sha"]
    artifacts = [item["execution_config"], item["execution_auth"], item["grant"], item["approval"]]
    return item["repository"]["origin_main_sha"] == sha and all(a["repository_sha"] == sha for a in artifacts)


def test_current_head_binding_passes():
    item = report()
    assert item["repository"]["sha"] == "1fa9b1958993c9a89c6001036ead6fdb88064c28"
    assert item["repository"]["fresh"] is True
    assert validate_chain(item) is True
    assert item["binding_validation"]["all_artifact_sha_match"] is True


def test_old_sha_is_rejected():
    item = report()
    old = "2c6e702ccfd22685167f90d6b91dac391ac13046"
    item["execution_auth"]["repository_sha"] = old
    assert validate_chain(item) is False
    assert old in item["superseded_artifact_shas"]


def test_mixed_chain_is_rejected():
    item = report()
    item["grant"]["repository_sha"] = "33f3701945adb5140f3a9f6854d5f704701c0201"
    assert validate_chain(item) is False


def test_scope_mutation_is_rejected():
    item = report()
    item["scope"]["method"] = "POST"
    item["scope"]["endpoint"] = "/responses"
    assert item["scope"] != {"method": "GET", "endpoint": "/models", "max_requests": 1}
    assert item["binding_validation"]["scope_unchanged"] is True


def test_execution_remains_blocked_and_offline():
    item = report()
    assert item["execution_status"] == "BLOCKED"
    assert item["execution_authorization"] == "NOT GRANTED"
    assert item["credential_status"] == "NOT_PROVIDED"
    assert all(value == 0 for value in item["offline_counters"].values())


def test_scope_audit_is_clean():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
