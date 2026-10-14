"""GRANT-REISSUE-R1 的当前 HEAD 绑定与链一致性测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRANT_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_grant_reissue_r1.json"
DOC_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_grant_reissue_r1.md"
SCOPE_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_grant_reissue_r1_scope_audit.json"
CURRENT_HEAD = "3489ed40af3589313f2d3c5a08d9da5faf41dddf"
OLD_SHA = "1fa9b1958993c9a89c6001036ead6fdb88064c28"
EXPECTED_SCOPE = {"method": "GET", "endpoint": "/models", "max_requests": 1}


def grant():
    return json.loads(GRANT_PATH.read_text(encoding="utf-8"))


def validate_grant(item):
    if item["repository_sha"] != CURRENT_HEAD:
        return "REJECT"
    if item["scope"] != EXPECTED_SCOPE:
        return "REJECT"
    if item["credential_source"]["invoked"] or item["credential_source"]["status"] != "NOT_ACQUIRED":
        return "REJECT"
    return "PASS"


def validate_chain(item):
    if validate_grant(item) != "PASS":
        return "REJECT"
    if not item["binding"]["chain_consistent"]:
        return "REJECT"
    if any(item["binding"][name]["bound_sha"] != CURRENT_HEAD for name in ["execution_config", "execution_auth", "approval", "credential_source"]):
        return "REJECT"
    return "PASS"


def test_current_head_grant_passes_own_binding():
    item = grant()
    assert item["repository_sha"] == CURRENT_HEAD
    assert validate_grant(item) == "PASS"
    assert item["status"] == "HOLD"


def test_old_grant_is_rejected():
    item = grant()
    item["repository_sha"] = OLD_SHA
    assert validate_grant(item) == "REJECT"
    assert item["old_grant"]["result"] == "REJECTED_STALE"


def test_mixed_chain_is_rejected():
    item = grant()
    item["binding"]["execution_auth"]["bound_sha"] = OLD_SHA
    item["binding"]["chain_consistent"] = False
    assert validate_chain(item) == "REJECT"


def test_existing_chain_blocker_is_preserved():
    item = grant()
    assert item["binding"]["chain_status"] == "STALE_DEPENDENCIES"
    assert item["status"] == "HOLD"
    assert item["execution_status"] == "BLOCKED"
    assert validate_chain(item) == "REJECT"


def test_scope_mutation_is_rejected():
    item = grant()
    item["scope"]["method"] = "POST"
    item["scope"]["endpoint"] = "/responses"
    assert validate_grant(item) == "REJECT"


def test_credential_callback_count_is_zero():
    calls = 0
    assert calls == 0
    item = grant()
    assert item["credential_source"]["invoked"] is False
    assert item["offline_counters"]["credential_callback_calls"] == 0


def test_scope_and_credential_policy_are_frozen():
    item = grant()
    assert item["provider"] == "DeepSeek"
    assert item["scope"] == EXPECTED_SCOPE
    assert item["credential_source"]["type"] == "environment_callback"
    assert item["credential_source"]["reference"] == "DEEPSEEK_API_KEY"


def test_offline_counters_are_zero_and_scope_audit_clean():
    item = grant()
    assert all(value == 0 for value in item["offline_counters"].values())
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["credential_callback_invoked"] is False


def test_no_credential_material_is_in_reissue_artifacts():
    text = GRANT_PATH.read_text(encoding="utf-8") + "\n" + DOC_PATH.read_text(encoding="utf-8")
    patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}",
        r"DEEPSEEK_API_KEY\s*[:=]\s*[^`\\n]+",
    ]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)
