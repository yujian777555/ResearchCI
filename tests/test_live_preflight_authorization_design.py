"""LIVE-PREFLIGHT-AUTH-R0 的纯离线授权设计测试。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "agentbench/reports/phase2b_ds1_live_preflight_auth_r0_schema.json").read_text(encoding="utf-8"))


def evaluate(approval, *, repository_sha, protocol_hash, now, consumed=False):
    scope = approval.get("allowed_scope", {})
    if consumed:
        return "REJECT"
    if approval.get("status") != "APPROVED":
        return "REJECT"
    if approval.get("repository_sha") != repository_sha or approval.get("protocol_hash") != protocol_hash:
        return "REJECT"
    if approval.get("expires_at") <= now:
        return "REJECT"
    if scope != {"provider": "DeepSeek", "method": "GET", "endpoint": "/models", "max_requests": 1}:
        return "REJECT"
    return "APPROVED"


def valid_approval():
    now = datetime.now(timezone.utc)
    return {
        "status": "APPROVED",
        "run_id": "run-design-r0",
        "repository_sha": "a" * 40,
        "protocol_hash": "sha256:" + "b" * 64,
        "expires_at": now + timedelta(minutes=5),
        "allowed_scope": {"provider": "DeepSeek", "method": "GET", "endpoint": "/models", "max_requests": 1},
    }, now


def test_valid_approval_is_approved():
    approval, now = valid_approval()
    assert evaluate(approval, repository_sha="a" * 40, protocol_hash="sha256:" + "b" * 64, now=now) == "APPROVED"


def test_post_responses_scope_is_rejected():
    approval, now = valid_approval()
    approval["allowed_scope"]["method"] = "POST"
    approval["allowed_scope"]["endpoint"] = "/responses"
    assert evaluate(approval, repository_sha="a" * 40, protocol_hash="sha256:" + "b" * 64, now=now) == "REJECT"


def test_expired_approval_is_rejected():
    approval, now = valid_approval()
    approval["expires_at"] = now - timedelta(seconds=1)
    assert evaluate(approval, repository_sha="a" * 40, protocol_hash="sha256:" + "b" * 64, now=now) == "REJECT"


def test_revoked_status_is_rejected():
    approval, now = valid_approval()
    approval["status"] = "REVOKED"
    assert evaluate(approval, repository_sha="a" * 40, protocol_hash="sha256:" + "b" * 64, now=now) == "REJECT"


def test_repository_mismatch_is_rejected():
    approval, now = valid_approval()
    assert evaluate(approval, repository_sha="c" * 40, protocol_hash="sha256:" + "b" * 64, now=now) == "REJECT"


def test_protocol_mismatch_is_rejected():
    approval, now = valid_approval()
    assert evaluate(approval, repository_sha="a" * 40, protocol_hash="sha256:" + "c" * 64, now=now) == "REJECT"


def test_consumed_approval_cannot_be_reused():
    approval, now = valid_approval()
    assert evaluate(approval, repository_sha="a" * 40, protocol_hash="sha256:" + "b" * 64, now=now, consumed=True) == "REJECT"


def test_credential_policy_is_callback_memory_only():
    policy = SPEC["credential_policy"]
    assert policy["source"] == "approved_callback_only"
    assert policy["lifetime"] == "temporary_memory_only"
    assert policy["discard_after_request"] is True
    assert set(policy["forbidden_persistence"]) == {"api_key", "token", "Authorization header", "raw secret"}


def test_evidence_policy_excludes_secrets():
    forbidden = set(SPEC["evidence_bundle"]["forbidden_fields"])
    assert {"credential", "secret", "api_key", "token", "authorization_header", "raw_response_body"} <= forbidden
    assert SPEC["evidence_bundle"]["hash_chain_required"] is True


def test_current_state_has_no_execution_authorization():
    current = SPEC["current_authorization"]
    assert current["status"] == "NOT_GRANTED"
    assert current["live_execution"] == "BLOCKED"
    assert current["planner_approval_present"] is False
    assert current["credential_present"] is False
    assert current["real_provider_request_performed"] is False
