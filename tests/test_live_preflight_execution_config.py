"""EXECUTION-CONFIG-R0 的离线配置组合测试。"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_config_r0.json"
SCOPE = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_config_r0_scope_audit.json"


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def evaluate(item):
    if item["runtime"]["name"] != "Linux WSL2 Ubuntu-22.04" or not item["runtime"]["validated"]:
        return "BLOCKED"
    if item["approval_chain"]["grant"] != "GRANTED":
        return "BLOCKED"
    if item["credential_policy"]["mode"] != "callback_only" or item["credential_policy"]["persistence"] or not item["credential_policy"].get("approved_source", False):
        return "BLOCKED"
    if item["request"] != {"method": "GET", "endpoint": "/models", "max_requests": 1}:
        return "BLOCKED"
    return "EXECUTION_CONFIG_READY"


def test_valid_mocked_config_is_ready():
    item = config()
    item["approval_chain"]["grant"] = "GRANTED"
    item["credential_policy"]["approved_source"] = True
    assert evaluate(item) == "EXECUTION_CONFIG_READY"


def test_missing_grant_blocks():
    assert config()["approval_chain"]["grant"] == "HOLD"
    assert evaluate(config()) == "BLOCKED"


def test_missing_credential_status_blocks():
    item = config()
    item["approval_chain"]["grant"] = "GRANTED"
    item["credential_policy"]["approved_source"] = False
    assert evaluate(item) == "BLOCKED"


def test_runtime_mismatch_blocks():
    item = config()
    item["runtime"]["name"] = "Windows"
    assert evaluate(item) == "BLOCKED"


def test_scope_mutation_blocks():
    item = config()
    item["request"]["method"] = "POST"
    item["request"]["endpoint"] = "/responses"
    assert evaluate(item) == "BLOCKED"


def test_bindings_and_forbidden_transitions_are_frozen():
    item = config()
    assert item["repository"]["sha"] == "62c5eb67ecde46b5204b7581c20a1542273dbf67"
    assert item["protocol"]["deepseek_hash"].startswith("sha256:")
    assert item["protocol"]["stats_hash"].startswith("sha256:")
    assert ["BLOCKED", "EXECUTE"] in item["state"]["forbidden_transitions"]
    assert ["INVALID", "READY"] in item["state"]["forbidden_transitions"]


def test_scope_audit_and_offline_counters_are_clean():
    scope = json.loads(SCOPE.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["historical_reports_modified"] is False
    assert all(value == 0 for value in config()["offline_counters"].values())
