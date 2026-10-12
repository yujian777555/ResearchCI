"""LIVE-PREFLIGHT-DESIGN-R0 的离线协议测试。"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "agentbench/reports/phase2b_ds1_live_preflight_design_r0_state_machine.json").read_text(encoding="utf-8"))
STATES = set(SPEC["states"])
ALLOWED = {tuple(item) for item in SPEC["allowed_transitions"]}
FORBIDDEN = {tuple(item) for item in SPEC["forbidden_transitions"]}


def test_normal_state_flow_reaches_completed():
    flow = [
        "CREATED", "AUTHORIZED", "FRESHNESS_VERIFIED", "RESERVED",
        "CREDENTIAL_ACQUIRED", "TRANSPORT_READY", "HTTP_STARTED",
        "RESULT_RECEIVED", "RESULT_PERSISTED", "COMPLETED",
    ]
    assert all(state in STATES for state in flow)
    assert set(zip(flow, flow[1:])) == ALLOWED


def test_invalid_state_transitions_are_rejected():
    for transition in [("CREATED", "HTTP_STARTED"), ("UNKNOWN", "RETRY"), ("RESULT_PERSISTED", "HTTP_STARTED"), ("COMPLETED", "RESERVED")]:
        assert transition in FORBIDDEN
        assert transition not in ALLOWED


def test_terminal_states_have_no_normal_outgoing_edges():
    terminals = set(SPEC["terminal_states"])
    assert terminals == {"COMPLETED", "REJECTED", "UNKNOWN", "ABORTED"}
    assert all(source not in terminals for source, _ in ALLOWED)


def test_endpoint_allowlist_is_single_get_models():
    contract = SPEC["request_contract"]
    assert contract["method"] == "GET"
    assert contract["path"] == "/models"
    assert contract["max_provider_requests"] == 1
    assert "/responses" in contract["forbidden_paths"]
    assert "POST" in contract["forbidden_methods"]


def test_identity_binding_is_complete():
    assert set(SPEC["identity_binding"]) == {
        "run_id", "authorization_id", "token_id", "repository_sha",
        "protocol_hash", "transport_mode", "endpoint", "allowed_method", "allowed_path",
    }


def test_evidence_policy_excludes_secrets_and_body():
    evidence = SPEC["evidence_bundle"]
    forbidden = set(evidence["forbidden_fields"])
    assert {"api_key", "authorization_header", "raw_credential", "full_response_body", "token_value"} <= forbidden
    assert evidence["redaction_required"] is True
    assert evidence["hash_chain_required"] is True
    assert evidence["atomic_summary_required"] is True


def test_failure_semantics_are_fail_closed():
    failures = SPEC["failure_transitions"]
    assert failures["authorization_invalid"] == "REJECTED"
    assert failures["repository_changed"] == "REJECTED"
    assert failures["ledger_conflict"] == "REJECTED"
    assert failures["credential_failure"] == "UNKNOWN"
    assert failures["network_timeout"] == "UNKNOWN"
    assert failures["provider_5xx"] == "UNKNOWN"


def test_unknown_and_completed_are_not_reusable():
    reservation = SPEC["reservation"]
    assert reservation["one_use"] is True
    assert reservation["reconsume_after_unknown"] is False
    assert reservation["reconsume_after_completed"] is False
    assert ["UNKNOWN", "RESERVED"] in SPEC["forbidden_transitions"]
    assert ["COMPLETED", "RESERVED"] in SPEC["forbidden_transitions"]


def test_preconditions_cover_runtime_approval_and_audit_sink():
    assert set(SPEC["preconditions"]) == {
        "windows_linux_runtime_qualification_accepted",
        "planner_explicit_approval",
        "signed_authorization_exists",
        "fresh_repository_proof",
        "one_use_ledger_available",
        "credential_source_approved",
        "endpoint_allowlist_verified",
        "audit_sink_writable",
    }


def test_design_has_zero_live_activity():
    assert SPEC["status"] == "DESIGNED_OFFLINE"
    assert SPEC["offline_counters"] == {
        "real_provider_api_calls": 0,
        "real_provider_network_calls": 0,
        "real_credential_reads": 0,
        "live_canary_episodes": 0,
        "benchmark_episodes": 0,
    }
