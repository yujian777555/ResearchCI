"""CREDENTIAL-PROVISION-R0 的纯设计与生命周期测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_credential_provision_r0.json"
DOC_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_credential_provision_r0.md"
SCOPE_PATH = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_credential_provision_r0_scope_audit.json"


def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def attempt(action, *, approval=True, credential=True, scope=True, destroyed=False):
    if not approval:
        return "HOLD"
    if not scope or destroyed:
        return "REJECT"
    if not credential:
        return "HOLD"
    return "PASS" if action == "callback_only" else "REJECT"


def test_callback_only():
    item = schema()
    assert item["mode"] == "callback_only"
    assert item["storage"] == "memory_only"
    assert attempt("callback_only") == "PASS"


def test_persistence_attempt_is_rejected():
    assert attempt("write_disk") == "REJECT"
    assert item_forbidden("disk")


def test_logging_attempt_is_rejected():
    assert attempt("write_logs") == "REJECT"
    assert item_forbidden("logs")


def test_scope_mutation_is_rejected():
    assert attempt("callback_only", scope=False) == "REJECT"
    assert schema()["scope"] == {"method": "GET", "endpoint": "/models", "max_requests": 1}


def test_reuse_after_destroy_is_rejected():
    assert attempt("callback_only", destroyed=True) == "REJECT"
    assert ["DESTROYED", "IN_MEMORY"] in schema()["forbidden_transitions"]
    assert ["DESTROYED", "CONSUMED"] in schema()["forbidden_transitions"]


def test_missing_approval_is_hold():
    assert attempt("callback_only", approval=False) == "HOLD"


def test_failure_semantics_are_unknown_without_retry():
    failure = schema()["failure_semantics"]
    assert all(failure[key] == "UNKNOWN" for key in ["callback_failure", "partial_acquisition", "transport_uncertainty", "destroy_failure", "unexpected_exception"])
    assert failure["automatic_retry"] is False


def test_destroy_conditions_cover_all_exit_paths():
    assert set(schema()["destroy_conditions"]) == {"request_completed", "request_failed", "timeout", "abort", "exception", "destroy_failure"}


def test_secret_scan_has_no_material_or_auth_header():
    text = SCHEMA_PATH.read_text(encoding="utf-8") + "\n" + DOC_PATH.read_text(encoding="utf-8")
    patterns = [r"sk-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", r"Authorization:\s*[A-Za-z0-9._~+/=-]{12,}", r"secret\s+value"]
    assert all(re.search(pattern, text, flags=re.IGNORECASE) is None for pattern in patterns)


def test_current_status_and_scope_audit():
    item = schema()
    assert item["current_status"] == {"credential": "NOT PROVIDED", "execution_authorization": "NOT GRANTED", "live_activation": "BLOCKED"}
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    assert scope["forbidden_changes_detected"] is False
    assert scope["credential_callback_invoked"] is False
    assert all(value == 0 for value in scope.values() if isinstance(value, int))


def item_forbidden(destination):
    return destination in schema()["forbidden_destinations"]
