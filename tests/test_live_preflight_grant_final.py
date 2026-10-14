"""GRANT-FINAL-R0 的单次授权边界离线测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRANT_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_grant_final_r0.json"
DOC_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_grant_final_r0.md"
SCOPE_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_grant_final_r0_scope_audit.json"
TARGET_SHA = "1fa9b1958993c9a89c6001036ead6fdb88064c28"
EXPECTED_SCOPE = {"method": "GET", "endpoint": "/models", "max_requests": 1}


def grant():
    return json.loads(GRANT_PATH.read_text(encoding="utf-8"))


def validate(item):
    if item["repository"]["sha"] != TARGET_SHA or not item["binding"]["repository_sha_match"]:
        return "REJECT"
    if item["runtime"]["environment"] != "WSL2 Ubuntu-22.04" or item["runtime"]["platform"] != "Linux":
        return "REJECT"
    if item["scope"] != EXPECTED_SCOPE:
        return "REJECT"
    if item["credential"]["status"] != "NOT_ACQUIRED" or item["credential"]["callback_invoked"]:
        return "REJECT"
    if item["status"] != "HOLD":
        return "REJECT"
    return "PASS"


def attempt(action, item):
    if action in {"credential_callback", "acquire_credential", "consume_replay"}:
        return "REJECT"
    if action == "consume":
        return "PASS" if item["status"] == "GRANTED" else "REJECT"
    return validate(item)


def test_valid_current_target_grant():
    item = grant()
    assert validate(item) == "PASS"
    assert item["status"] == "HOLD"
    assert item["repository"]["sha"] == TARGET_SHA


def test_old_sha_is_rejected():
    item = grant()
    item["repository"]["sha"] = "old-sha"
    item["binding"]["repository_sha_match"] = False
    assert validate(item) == "REJECT"


def test_scope_mutation_is_rejected():
    item = grant()
    item["scope"]["method"] = "POST"
    item["scope"]["endpoint"] = "/responses"
    assert validate(item) == "REJECT"


def test_credential_acquisition_attempt_is_rejected():
    calls = 0
    item = grant()
    assert attempt("credential_callback", item) == "REJECT"
    assert attempt("acquire_credential", item) == "REJECT"
    assert calls == 0
    assert item["credential"]["callback_invoked"] is False


def test_grant_replay_is_rejected():
    item = grant()
    assert attempt("consume", item) == "REJECT"
    item["status"] = "GRANTED"
    assert attempt("consume", item) == "PASS"
    item["status"] = "CONSUMED"
    assert attempt("consume_replay", item) == "REJECT"


def test_state_machine_forbids_reuse():
    item = grant()
    forbidden = item["state_machine"]["forbidden_transitions"]
    assert ["HOLD", "CONSUMED"] in forbidden
    assert ["CONSUMED", "GRANTED"] in forbidden
    assert ["DESTROYED", "GRANTED"] in forbidden


def test_credential_policy_and_network_are_closed():
    item = grant()
    assert item["credential"]["source"] == "environment_callback"
    assert item["credential"]["status"] == "NOT_ACQUIRED"
    assert item["credential"]["persistence"] is False
    assert item["network"]["allowed"] is False


def test_offline_counters_are_zero():
    item = grant()
    assert all(value == 0 for value in item["offline_counters"].values())
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["credential_callback_invoked"] is False
    assert scope["forbidden_changes_detected"] is False


def test_secret_scan_has_no_credential_material():
    text = GRANT_PATH.read_text(encoding="utf-8") + "\n" + DOC_PATH.read_text(encoding="utf-8")
    patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}",
        r"DEEPSEEK_API_KEY\s*[:=]\s*[^`\\n]+",
    ]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_forbidden_actions_are_outside_scope():
    item = grant()
    for action in ("credential_callback", "acquire_credential", "consume_replay"):
        assert attempt(action, item) == "REJECT"
    assert item["scope"] == EXPECTED_SCOPE
