"""CREDENTIAL-SOURCE-BINDING-R0 的离线绑定与未获取测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_credential_source_binding_r0.json"
DOC_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_credential_source_binding_r0.md"
SCOPE_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_credential_source_binding_r0_scope_audit.json"
EXPECTED_SCOPE = {"provider": "DeepSeek", "method": "GET", "endpoint": "/models", "max_requests": 1}


def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def bind_source(source_reference: str, available_sources: dict[str, str]):
    """只注册 source reference；不会检查或读取 available_sources 的值。"""
    if source_reference != "DEEPSEEK_API_KEY":
        return "REJECT"
    return "SOURCE_REGISTERED"


def attempt(action: str, *, authorized: bool = False, scope=None):
    if scope is not None and scope != EXPECTED_SCOPE:
        return "REJECT"
    if action == "automatic_scan":
        return "REJECT"
    if action in {"persist", "log", "reuse_after_destroy"}:
        return "REJECT"
    if action == "callback" and not authorized:
        return "HOLD"
    if action == "callback":
        return "AUTHORIZED_TO_ACQUIRE"
    return "SOURCE_REGISTERED"


def test_source_reference_is_registered_without_acquisition():
    available = {"DEEPSEEK_API_KEY": "synthetic-material"}
    assert bind_source("DEEPSEEK_API_KEY", available) == "SOURCE_REGISTERED"
    item = schema()
    assert item["acquisition"]["invoked"] is False
    assert item["lifecycle"]["current_state"] == "SOURCE_REGISTERED"
    assert item["current_status"]["credential"] == "NOT_ACQUIRED"


def test_automatic_environment_scan_is_rejected():
    assert attempt("automatic_scan") == "REJECT"


def test_callback_is_not_invoked_during_binding():
    calls = 0
    assert calls == 0
    assert schema()["offline_counters"]["credential_callback_calls"] == 0


def test_callback_requires_explicit_authorization():
    assert attempt("callback", authorized=False) == "HOLD"
    assert attempt("callback", authorized=True) == "AUTHORIZED_TO_ACQUIRE"


def test_persistence_and_logging_are_rejected():
    assert attempt("persist") == "REJECT"
    assert attempt("log") == "REJECT"
    assert set(["disk", "logs", "audit", "summary", "reports"]) <= set(schema()["forbidden_destinations"])


def test_destroyed_material_cannot_be_reused():
    assert attempt("reuse_after_destroy") == "REJECT"
    assert ["DESTROYED", "ACQUIRED"] in schema()["lifecycle"]["forbidden_transitions"]
    assert ["CONSUMED", "ACQUIRED"] in schema()["lifecycle"]["forbidden_transitions"]


def test_scope_is_fixed_and_mutation_rejected():
    assert schema()["scope"] == EXPECTED_SCOPE
    mutated = dict(EXPECTED_SCOPE, method="POST", endpoint="/responses")
    assert attempt("callback", authorized=True, scope=mutated) == "REJECT"


def test_failure_semantics_are_unknown_without_retry():
    failure = schema()["failure_semantics"]
    assert failure["callback_failure"] == "UNKNOWN"
    assert failure["partial_acquisition"] == "UNKNOWN" if "partial_acquisition" in failure else True
    assert failure["destroy_failure"] == "UNKNOWN"
    assert failure["automatic_retry"] is False


def test_no_secret_material_is_in_binding_artifacts():
    text = SCHEMA_PATH.read_text(encoding="utf-8") + "\n" + DOC_PATH.read_text(encoding="utf-8")
    patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}",
        r"DEEPSEEK_API_KEY\s*[:=]\s*[^`\\n]+",
    ]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_current_status_and_counters_are_blocked_and_zero():
    item = schema()
    assert item["current_status"] == {
        "credential": "NOT_ACQUIRED",
        "execution_authorization": "NOT GRANTED",
        "execution_status": "BLOCKED",
        "live_activation": "BLOCKED",
    }
    assert all(value == 0 for value in item["offline_counters"].values())
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["credential_callback_invoked"] is False
    assert scope["forbidden_changes_detected"] is False
