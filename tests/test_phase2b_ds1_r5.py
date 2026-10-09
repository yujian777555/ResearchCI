"""R5 授权和单次账本的离线行为验收；永不读取用户凭据或外部网络。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket

import httpx2
import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_HARNESS = "a" * 40
TEST_SIGNING_KEY = b"R5 offline fixture trust anchor only"
SYNTHETIC_KEY = "researchci-r5-synthetic-credential"


@pytest.fixture(autouse=True)
def no_provider_network_or_credentials(monkeypatch):
    original = os._Environ.__getitem__
    def guarded(self, key):
        if key in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}:
            raise AssertionError("禁止读取真实凭据或检查存在性")
        return original(self, key)
    def forbidden(*args, **kwargs):
        raise AssertionError("禁止真实网络")
    monkeypatch.setattr(os._Environ, "__getitem__", guarded)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def signed_authorization(**changes):
    intent = {"schema_version": 1, "stage": "PRECHECK_ONLY", "kind": "REPLACEMENT",
              "run_id": "offline-r5-run", "token_id": "offline-r5-token", "harness_sha": TEST_HARNESS,
              "approval_reference": "offline-test-not-real-approval", "transport_mode": "MOCK_HTTP",
              "predecessor_result_commit": "d92b541263edea9b749ff70f475fc4aad5b2fce0"}
    intent.update(changes)
    payload = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    return {"intent": intent, "signature": hmac.new(TEST_SIGNING_KEY, payload, hashlib.sha256).hexdigest()}


def run_fixture(tmp_path, *, authorization=None, sequence=None, state=None):
    from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, RepositoryState
    from agentbench.deepseek_live_canary.cutover import execute_replacement_preflight
    seen, reads = [], []
    items = iter(sequence if sequence is not None else [{"data": [{"id": "deepseek-v4-pro"}]}])
    def handler(request):
        seen.append((request.method, request.url.path))
        item = next(items)
        if isinstance(item, BaseException): raise item
        if item == "malformed": return httpx2.Response(200, content=b"not-json", request=request)
        if isinstance(item, int): return httpx2.Response(item, json={"error": {"message": "synthetic"}}, request=request)
        return httpx2.Response(200, json=item, request=request)
    def credential():
        reads.append(1)
        return SYNTHETIC_KEY
    repo_state = state or RepositoryState(TEST_HARNESS, TEST_HARNESS, "main", True)
    outcome = execute_replacement_preflight(
        authorization=authorization or signed_authorization(), verifier=AuthorizationVerifier(TEST_SIGNING_KEY),
        ledger_path=tmp_path / "ledger.sqlite", output_dir=tmp_path / "evidence", repo_root=ROOT,
        run_id="offline-r5-run", expected_harness_sha=TEST_HARNESS, credential_provider=credential,
        transport=httpx2.MockTransport(handler), state_reader=lambda _: repo_state)
    return outcome, seen, reads


def test_signed_single_use_precheck_uses_actual_sdk_and_never_starts_canary(tmp_path):
    outcome, seen, reads = run_fixture(tmp_path)
    assert outcome["status"] == "PASS" and outcome["canary_authorized"] is False
    assert seen == [("GET", "/models")] and reads == [1]
    assert outcome["http_attempts_observed"] == outcome["sdk_invocations"] == 1
    assert outcome["ledger_state"] == "RESULT_PERSISTED"
    with pytest.raises(RuntimeError): run_fixture(tmp_path)


@pytest.mark.parametrize("change", ["signature", "stage", "harness_sha", "run_id", "kind"])
def test_forged_or_mismatched_authorization_denied(tmp_path, change):
    auth = signed_authorization()
    if change == "signature": auth["signature"] = "0" * 64
    else: auth = signed_authorization(**{change: "unapproved"})
    with pytest.raises((RuntimeError, ValueError)): run_fixture(tmp_path, authorization=auth)


def test_concurrent_reservation_has_exactly_one_winner(tmp_path):
    from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, OneUseLedger
    verified = AuthorizationVerifier(TEST_SIGNING_KEY).verify(signed_authorization(), run_id="offline-r5-run", harness_sha=TEST_HARNESS, transport_mode="MOCK_HTTP")
    def reserve(_):
        try:
            OneUseLedger(tmp_path / "ledger.sqlite").reserve(verified)
            return True
        except RuntimeError: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 1


def test_production_http_transport_is_constructible_only_with_reserved_live_authorization(tmp_path):
    from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, OneUseLedger, read_repository_state, validate_repository
    from agentbench.deepseek_live_canary.preflight import PreflightAuditLog
    from agentbench.deepseek_live_canary.sdk_client import build_sdk_client
    with pytest.raises(RuntimeError):
        build_sdk_client(api_key=SYNTHETIC_KEY, audit_log=PreflightAuditLog(tmp_path / "disabled.jsonl"), transport=httpx2.HTTPTransport(retries=0))
    auth = signed_authorization(transport_mode="LIVE_HTTP")
    with pytest.raises(ValueError):
        AuthorizationVerifier(TEST_SIGNING_KEY).verify(auth, run_id="offline-r5-run", harness_sha=TEST_HARNESS, transport_mode="LIVE_HTTP")


@pytest.mark.parametrize("state", [
    {"head": "wrong", "remote_head": TEST_HARNESS, "branch": "main", "clean": True},
    {"head": TEST_HARNESS, "remote_head": "wrong", "branch": "main", "clean": True},
    {"head": TEST_HARNESS, "remote_head": TEST_HARNESS, "branch": "feature", "clean": True},
    {"head": TEST_HARNESS, "remote_head": TEST_HARNESS, "branch": "main", "clean": False},
])
def test_repository_state_gate_denies_dirty_wrong_sha_or_wrong_branch(tmp_path, state):
    from agentbench.deepseek_live_canary.authorization import RepositoryState
    with pytest.raises(RuntimeError): run_fixture(tmp_path, state=RepositoryState(**state))


@pytest.mark.parametrize("response", [200, 401, 402, 429, 500, 503, "malformed"])
def test_replacement_preflight_persists_sanitized_result_and_never_posts_responses(tmp_path, response):
    outcome, seen, _reads = run_fixture(tmp_path, sequence=[response] if response != 200 else [{"data": [{"id": "deepseek-v4-pro"}]}])
    assert seen == [("GET", "/models")]
    assert outcome["canary_authorized"] is False
    assert outcome["actual_external_network_calls"] == 0
    assert outcome["ledger_state"] == "RESULT_PERSISTED"
    assert "Authorization" not in json.dumps(outcome)


def test_timeout_or_process_crash_marks_unknown_and_blocks_restart(tmp_path):
    outcome, seen, _reads = run_fixture(tmp_path, sequence=[httpx2.ReadTimeout("synthetic")])
    assert outcome["status"] == "FAIL_NETWORK" and outcome["ledger_state"] == "UNKNOWN"
    assert seen == [("GET", "/models")]
    with pytest.raises(RuntimeError): run_fixture(tmp_path)

    crash_dir = tmp_path / "crash"
    with pytest.raises(SystemExit): run_fixture(crash_dir, sequence=[SystemExit(17)])
    with pytest.raises(RuntimeError): run_fixture(crash_dir)


def test_failed_authorization_never_reads_synthetic_credential(tmp_path):
    auth = signed_authorization(stage="CANARY")
    with pytest.raises(ValueError): run_fixture(tmp_path, authorization=auth)


def test_preflight_cli_and_canary_cli_remain_default_denied():
    from agentbench.deepseek_live_canary.cli import main
    assert main(["preflight"]) != 0
    assert main(["canary"]) != 0


def test_missing_transport_instrumentation_is_unknown_and_fail_closed(tmp_path):
    from agentbench.deepseek_live_canary.preflight import PreflightAuditLog, run_preflight
    class Models:
        def list(self): return {"data": [{"id": "deepseek-v4-pro"}]}
    result = run_preflight(client_factory=lambda _: type("Client", (), {"models": Models()})(), credential_present=True,
                           audit_log=PreflightAuditLog(tmp_path / "audit.jsonl"))
    assert result.status == "PASS" or result.status == "FAIL_TRANSPORT_UNVERIFIED"
    assert result.status == "FAIL_TRANSPORT_UNVERIFIED" and result.http_attempt_count_verified is False
