from __future__ import annotations

import json
import os
from pathlib import Path

import httpx2
import pytest

from agentbench.deepseek_live_canary.preflight import PreflightAuditLog, atomic_write_json
from agentbench.deepseek_live_canary.sdk_client import build_sdk_client
from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier
from tests.test_phase2b_ds1_r5 import signed_authorization, TEST_HARNESS, TEST_SIGNING_KEY, SYNTHETIC_KEY, ROOT


def test_audit_symlink_parent_and_preexisting_temp_fail_closed(tmp_path):
    target=tmp_path/"target.jsonl"; target.write_text("safe\n")
    link=tmp_path/"audit.jsonl"
    try: link.symlink_to(target)
    except OSError: pytest.skip("symlink unavailable on this Windows host")
    with pytest.raises(RuntimeError): PreflightAuditLog(link).append({"event":"x"})
    parent_link=tmp_path/"parent"; real=tmp_path/"real"; real.mkdir()
    try: parent_link.symlink_to(real, target_is_directory=True)
    except OSError: pytest.skip("directory symlink unavailable")
    with pytest.raises(RuntimeError): PreflightAuditLog(parent_link/"audit.jsonl").append({"event":"x"})
    preexisting=tmp_path/"summary.json.tmp"; preexisting.write_text("attacker")
    with pytest.raises(RuntimeError): atomic_write_json(tmp_path/"summary.json", {"status":"PASS"})
    assert preexisting.read_text()=="attacker"


def test_summary_target_replacement_and_write_fault_fail_closed(tmp_path, monkeypatch):
    path=tmp_path/"summary.json"
    atomic_write_json(path, {"status":"PASS"})
    original=path.read_bytes()
    import agentbench.deepseek_live_canary.secure_io as secure_io
    monkeypatch.setattr(secure_io.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError): atomic_write_json(tmp_path/"new.json", {"status":"PASS"})
    assert path.read_bytes()==original


def test_live_v1_denied_before_credential_or_production_client(tmp_path):
    from agentbench.deepseek_live_canary.cutover import execute_replacement_preflight
    calls=[]
    with pytest.raises(ValueError):
        execute_replacement_preflight(authorization=signed_authorization(transport_mode="LIVE_HTTP"), verifier=AuthorizationVerifier(TEST_SIGNING_KEY), ledger_path=tmp_path/"ledger.sqlite", output_dir=tmp_path/"evidence", repo_root=ROOT, run_id="offline-r5-run", expected_harness_sha=TEST_HARNESS, credential_provider=lambda: calls.append(1) or SYNTHETIC_KEY, transport=httpx2.HTTPTransport(retries=0), state_reader=lambda _: type("State",(),{"head":TEST_HARNESS,"remote_head":TEST_HARNESS,"branch":"main","clean":True,"checked_remote_head":TEST_HARNESS,"remote_checked_at":__import__("time").monotonic()})())
    assert calls==[]


def test_live_client_v1_reservation_cannot_construct_transport(tmp_path):
    with pytest.raises(RuntimeError):
        build_sdk_client(api_key=SYNTHETIC_KEY, audit_log=PreflightAuditLog(tmp_path/"audit.jsonl"), transport=httpx2.HTTPTransport(retries=0))
