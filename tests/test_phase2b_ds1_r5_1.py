"""R5.1：离线远端新鲜度、授权绑定及跨进程/崩溃安全。"""
from __future__ import annotations

from dataclasses import replace
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import httpx2
import pytest

from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, OneUseLedger, RepositoryState, canonical
from tests.test_phase2b_ds1_r5 import signed_authorization, TEST_HARNESS, TEST_SIGNING_KEY, SYNTHETIC_KEY, ROOT


def approval():
    return AuthorizationVerifier(TEST_SIGNING_KEY).verify(signed_authorization(), run_id="offline-r5-run", harness_sha=TEST_HARNESS, transport_mode="MOCK_HTTP")


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    original = os._Environ.__getitem__
    def getitem(self, key):
        if key in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}: raise AssertionError("real credential read")
        return original(self, key)
    monkeypatch.setattr(os._Environ, "__getitem__", getitem)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: (_ for _ in ()).throw(AssertionError("external network")))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a: (_ for _ in ()).throw(AssertionError("external network")))


def test_terminal_ledger_state_cannot_be_reset_to_reserved(tmp_path):
    reservation = OneUseLedger(tmp_path / "ledger.sqlite").reserve(approval())
    reservation.transition("RESERVED", "UNKNOWN")
    with pytest.raises(RuntimeError): reservation.transition("UNKNOWN", "RESERVED")


def test_verified_object_payload_replacement_is_rejected(tmp_path):
    issued = approval()
    forged = replace(issued, payload=canonical(dict(issued.intent, run_id="forged")))
    with pytest.raises(RuntimeError): OneUseLedger(tmp_path / "ledger.sqlite").reserve(forged)


def test_ledger_tampered_result_is_rejected(tmp_path):
    reservation = OneUseLedger(tmp_path / "ledger.sqlite").reserve(approval())
    reservation.begin_http()
    reservation.transition("HTTP_STARTED", "RESULT_PERSISTED", {"status": "FAIL_AUTH"})
    with sqlite3.connect(reservation.ledger.path) as db:
        db.execute("UPDATE runs SET result=?", ('{"status":"PASS"}',))
    with pytest.raises(RuntimeError): reservation.validate("RESULT_PERSISTED")


def _reserve_process(path: str, queue):
    try:
        OneUseLedger(path).reserve(approval())
        queue.put(True)
    except BaseException:
        queue.put(False)


def _crash_after_reserve(path: str):
    OneUseLedger(path).reserve(approval())
    os._exit(17)


def test_sixteen_independent_processes_have_one_reservation_winner(tmp_path):
    context = mp.get_context("spawn")
    queue = context.Queue()
    processes = [context.Process(target=_reserve_process, args=(str(tmp_path / "ledger.sqlite"), queue)) for _ in range(16)]
    for process in processes: process.start()
    for process in processes: process.join(20)
    results = [queue.get(timeout=3) for _ in processes]
    assert sum(results) == 1 and all(process.exitcode == 0 for process in processes)


def test_process_exit_after_reservation_is_not_reusable(tmp_path):
    context = mp.get_context("spawn")
    process = context.Process(target=_crash_after_reserve, args=(str(tmp_path / "ledger.sqlite"),))
    process.start(); process.join(20)
    assert process.exitcode == 17
    with pytest.raises(RuntimeError): OneUseLedger(tmp_path / "ledger.sqlite").reserve(approval())


def test_database_locked_corrupt_and_unavailable_fail_closed(tmp_path):
    path = tmp_path / "locked.sqlite"
    ledger = OneUseLedger(path)
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(RuntimeError): OneUseLedger(path, timeout=0.05).reserve(approval())
    finally:
        db.rollback(); db.close()
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(RuntimeError): OneUseLedger(corrupt)
    directory = tmp_path / "directory.sqlite"
    directory.mkdir()
    with pytest.raises((RuntimeError, OSError)): OneUseLedger(directory)


def test_fresh_remote_sha_and_state_identity_gate_fail_closed():
    from agentbench.deepseek_live_canary.authorization import validate_repository
    now = time.monotonic()
    validate_repository(RepositoryState(TEST_HARNESS, TEST_HARNESS, "main", True, TEST_HARNESS, now), TEST_HARNESS, require_fresh=True)
    with pytest.raises(RuntimeError): validate_repository(RepositoryState(TEST_HARNESS, TEST_HARNESS, "main", True, "wrong", now), TEST_HARNESS, require_fresh=True)
    with pytest.raises(RuntimeError): validate_repository(RepositoryState(TEST_HARNESS, TEST_HARNESS, "main", True, TEST_HARNESS, now - 31), TEST_HARNESS, require_fresh=True)


def test_v2_public_key_authorization_is_bound_to_expiry_key_and_token(tmp_path):
    now = int(time.time())
    private, public, message, signature = [tmp_path / name for name in ("private.pem", "public.pem", "intent.json", "signature.bin")]
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    intent = {"schema_version": 2, "stage": "PRECHECK_ONLY", "kind": "REPLACEMENT", "run_id": "offline-r5-run", "token_id": "v2-token", "harness_sha": TEST_HARNESS, "approval_reference": "external-operator-record", "transport_mode": "MOCK_HTTP", "predecessor_result_commit": "d92b541263edea9b749ff70f475fc4aad5b2fce0", "key_id": "offline-key", "issued_at": now - 1, "expires_at": now + 300, "ledger_path": str((tmp_path / "ledger.sqlite").resolve())}
    message.write_text(canonical(intent), encoding="utf-8")
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(private), "-out", str(signature), str(message)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    authorization = {"intent": intent, "signature": signature.read_bytes().hex()}
    verifier = AuthorizationVerifier(public_key_pem=public.read_bytes(), key_id="offline-key", clock=lambda: now)
    verified = verifier.verify(authorization, run_id="offline-r5-run", harness_sha=TEST_HARNESS, transport_mode="MOCK_HTTP")
    verified.validate()
    with pytest.raises(ValueError): AuthorizationVerifier(public_key_pem=public.read_bytes(), key_id="offline-key", revoked_tokens={"v2-token"}, clock=lambda: now).verify(authorization, run_id="offline-r5-run", harness_sha=TEST_HARNESS, transport_mode="MOCK_HTTP")


def test_faults_before_audit_http_summary_and_ledger_commit_never_retry(tmp_path, monkeypatch):
    import agentbench.deepseek_live_canary.cutover as cutover
    from agentbench.deepseek_live_canary.preflight import PreflightAuditLog
    from tests.test_phase2b_ds1_r5 import run_fixture

    original_append = PreflightAuditLog.append
    calls = []
    def fail_transport_attempt(self, event):
        if event.get("event") == "transport_attempt": raise OSError("fsync fault")
        return original_append(self, event)
    monkeypatch.setattr(PreflightAuditLog, "append", fail_transport_attempt)
    with pytest.raises(BaseException): run_fixture(tmp_path / "audit-fault")
    assert not list((tmp_path / "audit-fault" / "evidence").glob("*.summary.json"))
    with pytest.raises(RuntimeError): run_fixture(tmp_path / "audit-fault")

    monkeypatch.undo()
    def fail_summary(*args, **kwargs): raise OSError("summary atomic write fault")
    monkeypatch.setattr(cutover, "persist_preflight_result", fail_summary)
    with pytest.raises(OSError): run_fixture(tmp_path / "summary-fault")
    with pytest.raises(RuntimeError): run_fixture(tmp_path / "summary-fault")


def test_repository_changes_between_checks_abort_before_http(tmp_path):
    from tests.test_phase2b_ds1_r5 import run_fixture
    states = [RepositoryState(TEST_HARNESS, TEST_HARNESS, "main", True), RepositoryState("changed", TEST_HARNESS, "main", True)]
    def state_reader(_): return states.pop(0)
    from agentbench.deepseek_live_canary.cutover import execute_replacement_preflight
    seen = []
    def handler(request): seen.append(request); return httpx2.Response(200, json={"data":[{"id":"deepseek-v4-pro"}]}, request=request)
    with pytest.raises(RuntimeError):
        execute_replacement_preflight(authorization=signed_authorization(), verifier=AuthorizationVerifier(TEST_SIGNING_KEY), ledger_path=tmp_path/"ledger.sqlite", output_dir=tmp_path/"evidence", repo_root=ROOT, run_id="offline-r5-run", expected_harness_sha=TEST_HARNESS, credential_provider=lambda: SYNTHETIC_KEY, transport=httpx2.MockTransport(handler), state_reader=state_reader)
    assert seen == []


def test_evidence_symlink_and_summary_temporary_link_are_rejected(tmp_path):
    from agentbench.deepseek_live_canary.preflight import atomic_write_json, PreflightAuditLog
    target = tmp_path / "target.txt"
    target.write_text("must remain intact")
    alias = tmp_path / "alias.jsonl"
    try:
        alias.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    with pytest.raises(RuntimeError): PreflightAuditLog(alias).append({"event": "test"})
    assert target.read_text() == "must remain intact"
    summary = tmp_path / "summary.json"
    summary.with_suffix(".json.tmp").symlink_to(target)
    with pytest.raises(RuntimeError): atomic_write_json(summary, {"status": "PASS"})
    assert target.read_text() == "must remain intact"


def test_sdk_header_cannot_leak_supplied_synthetic_secret(tmp_path):
    from agentbench.deepseek_live_canary.preflight import PreflightAuditLog, run_preflight, persist_preflight_result
    from agentbench.deepseek_live_canary.sdk_client import build_sdk_client
    log = PreflightAuditLog(tmp_path / "audit.jsonl")
    def handler(request):
        return httpx2.Response(200, json={"data": [{"id": "deepseek-v4-pro"}, {"id": "private_catalog_entry"}]},
                               headers={"x-request-id": SYNTHETIC_KEY}, request=request)
    client, _ = build_sdk_client(api_key=SYNTHETIC_KEY, audit_log=log, transport=httpx2.MockTransport(handler))
    try:
        result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
        persist_preflight_result(result, tmp_path / "summary.json", log)
    finally: client.close()
    text = log.path.read_text() + (tmp_path / "summary.json").read_text()
    assert SYNTHETIC_KEY not in text and "private_catalog_entry" not in text
