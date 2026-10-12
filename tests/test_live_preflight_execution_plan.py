"""LIVE-PREFLIGHT-EXECUTION-PLAN-R0 的离线计划测试。"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_plan_r0_checklist.json").read_text(encoding="utf-8"))


def evaluate_plan(*, runtime, approval, credential, scope, audit_sink):
    if runtime != "Linux" or not scope or not audit_sink:
        return "REJECT"
    if not approval or not credential:
        return "HOLD"
    return "READY"


def test_valid_plan_is_complete():
    assert PLAN["runtime_binding"]["distribution"] == "Ubuntu-22.04"
    assert PLAN["runtime_binding"]["filesystem"] == "native Linux filesystem"
    assert PLAN["execution_sequence"][-1] == "stop"
    assert len(PLAN["pre_execution_checklist"]["environment"]) == 5
    assert len(PLAN["pre_execution_checklist"]["authorization"]) == 5


def test_invalid_windows_runtime_is_rejected():
    assert evaluate_plan(runtime="Windows", approval=True, credential=True, scope=True, audit_sink=True) == "REJECT"


def test_invalid_scope_is_rejected():
    assert evaluate_plan(runtime="Linux", approval=True, credential=True, scope=False, audit_sink=True) == "REJECT"
    assert "POST /responses" in PLAN["request_limits"]["forbidden_actions"]


def test_missing_approval_is_hold():
    assert evaluate_plan(runtime="Linux", approval=False, credential=True, scope=True, audit_sink=True) == "HOLD"
    assert PLAN["execution_authorization"] == "NOT GRANTED"


def test_missing_credential_is_hold():
    assert evaluate_plan(runtime="Linux", approval=True, credential=False, scope=True, audit_sink=True) == "HOLD"


def test_request_limits_are_exact():
    limits = PLAN["request_limits"]
    assert limits["method"] == "GET"
    assert limits["endpoint"] == "/models"
    assert limits["max_requests"] == 1


def test_abort_conditions_fail_closed():
    abort = PLAN["abort_conditions"]
    assert abort["result_on_abort"] == "UNKNOWN"
    assert abort["retry_allowed"] is False
    assert abort["continue_allowed"] is False
    assert "redirect" in abort["network"]
    assert "audit write failure" in abort["evidence"]


def test_evidence_plan_and_credential_destruction_are_defined():
    evidence = PLAN["post_execution_evidence"]
    assert "run id" in evidence["allowed"]
    assert "raw token" in evidence["forbidden"]
    assert evidence["hash_chain_required"] is True
    assert evidence["atomic_summary_required"] is True
    assert evidence["credential_destroy_after_persist"] is True


def test_offline_counters_are_zero():
    assert PLAN["offline_counters"] == {
        "real_provider_api_calls": 0,
        "real_provider_network_calls": 0,
        "real_credential_reads": 0,
        "live_canary_episodes": 0,
        "benchmark_episodes": 0,
    }
