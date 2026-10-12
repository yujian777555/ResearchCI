"""最终 Live Preflight readiness 的离线一致性测试。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "agentbench/reports/phase2b_ds1_live_preflight_execution_readiness_r0.json"


def report():
    return json.loads(READINESS.read_text(encoding="utf-8"))


def evaluate(item):
    if not item["artifact_consistency"]["all_references_match"]:
        return "BLOCKED"
    if item["grant"]["status"] != "GRANTED" or item["credential"]["status"] != "APPROVED":
        return "BLOCKED"
    if not item["runtime"]["validated"] or not item["repository"]["fresh"]:
        return "BLOCKED"
    if item["scope"] != {"method": "GET", "endpoint": "/models", "max_requests": 1}:
        return "BLOCKED"
    return "READY_FOR_EXECUTION"


def test_missing_credential_blocks():
    assert report()["credential"]["status"] == "NOT_PROVIDED"
    assert evaluate(report()) == "BLOCKED"


def test_grant_hold_blocks():
    assert report()["grant"]["status"] == "HOLD"
    assert evaluate(report()) == "BLOCKED"


def test_hash_mismatch_blocks():
    item = report()
    item["artifact_consistency"]["all_references_match"] = False
    assert evaluate(item) == "BLOCKED"


def test_scope_mutation_blocks():
    item = report()
    item["scope"]["method"] = "POST"
    item["scope"]["endpoint"] = "/responses"
    assert evaluate(item) == "BLOCKED"


def test_all_valid_mocked_state_is_ready_without_execution():
    item = report()
    item["grant"]["status"] = "GRANTED"
    item["credential"]["status"] = "APPROVED"
    assert evaluate(item) == "READY_FOR_EXECUTION"
    assert report()["offline_counters"]["real_provider_api_calls"] == 0


def test_runtime_and_repository_are_bound():
    item = report()
    assert item["runtime"]["selected"] == "Linux WSL2 Ubuntu-22.04"
    assert item["runtime"]["validated"] is True
    assert item["repository"]["head"] == item["repository"]["origin_main"]
    assert item["repository"]["fresh"] is True


def test_source_hash_map_is_consistent_when_present():
    item = report()
    for path, expected in item["artifact_consistency"]["source_hashes"].items():
        assert "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
