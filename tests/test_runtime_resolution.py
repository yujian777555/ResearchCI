"""Runtime Resolution R0 的离线决策测试。"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = json.loads((ROOT / "agentbench/reports/phase2b_ds1_runtime_resolution_r0.json").read_text(encoding="utf-8"))


def test_runtime_decision_schema_selects_linux():
    assert REPORT["recommended_runtime"] == "Linux"
    assert REPORT["status"] == "RUNTIME_ACCEPTED: Linux"
    assert REPORT["selected_runtime"]["class"] == "Linux"
    assert REPORT["decision"] == "RUNTIME_ACCEPTED"
    assert REPORT["selected_runtime"]["distribution"] == "Ubuntu-22.04"
    assert REPORT["selected_runtime"]["kernel"] == REPORT["environment_verification"]["kernel"]
    policy = REPORT["qualification_scope"]
    assert policy["native_linux_evidence_storage_required"] is True
    assert policy["windows_mounted_storage_accepted"] is False
    assert policy["unqualified_linux_deployments_accepted"] is False


def test_linux_runtime_evidence_is_complete():
    evidence = REPORT["linux_evidence"]
    required = ["symlink", "toctou", "hardlink", "parent_replacement_audit_append", "parent_replacement_summary_write", "parent_replacement_evidence_publish", "audit_hash_chain", "summary_integrity"]
    assert all(evidence[key] == "PASS" for key in required)
    assert evidence["outside_target_modified"] is False
    ref = REPORT["evidence_references"]["linux"]
    source_path = ROOT / ref["path"]
    assert "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest() == ref["sha256"]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    assert source["counts"] == {"PASS": 8}
    assert source["environment"]["kernel"] == REPORT["selected_runtime"]["kernel"]
    assert source["environment"]["python"] == REPORT["selected_runtime"]["python"]
    for case in source["tests"]:
        assert case["result"] == "PASS"
        assert case["audit_hash_chain_valid"] is True
        assert case["summary_integrity"] is True
        assert case["outside_target_modified"] is False
    for path, expected in source["source_hashes"].items():
        assert "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected


def test_windows_blockers_are_preserved():
    windows = REPORT["windows_evidence"]
    assert windows["file_symlink"] == "ENVIRONMENT_BLOCKED"
    assert windows["directory_symlink"] == "ENVIRONMENT_BLOCKED"
    assert windows["parent_replacement"] == "ENVIRONMENT_LIMITED"
    assert "WinError 1314" in windows["blocking_reasons"]
    ref = REPORT["evidence_references"]["windows"]
    path = ROOT / ref["path"]
    assert "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
    source = json.loads(path.read_text(encoding="utf-8"))
    assert source["status"] == "WINDOWS_RUNTIME_VALIDATION_PENDING"
    assert source["counts"] == {"ENVIRONMENT_BLOCKED": 6, "PASS": 2}


def test_linux_security_impact_is_accepted_and_windows_pending():
    impact = REPORT["security_impact"]
    assert impact["linux_evidence_integrity"] == "ACCEPTED"
    assert impact["linux_toctou_protection"] == "ACCEPTED"
    assert impact["linux_runtime_qualification"] == "ACCEPTED"
    assert impact["windows_runtime_qualification"] == "PENDING"
    assert impact["windows_pending_blocks_selected_linux_filesystem_qualification"] is False


def test_blocker_preservation_and_no_execution_authorization():
    assert REPORT["execution_authorization"] == "NOT GRANTED"
    assert REPORT["live_activation"] == "BLOCKED"
    assert len(REPORT["blockers"]) >= 3
    assert REPORT["qualification_scope"]["filesystem_proof_is_execution_approval"] is False
    historical_path = ROOT / REPORT["evidence_references"]["authorization_decision"]["path"]
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    assert historical["decision"] == "HOLD"
    assert historical["execution_authorization"] == "NOT GRANTED"


def test_offline_counters_are_zero():
    assert REPORT["offline_counters"] == {
        "real_provider_api_calls": 0,
        "real_provider_network_calls": 0,
        "real_credential_reads": 0,
        "live_canary_episodes": 0,
        "benchmark_episodes": 0,
    }
