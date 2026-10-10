"""R5.1-R3：实际准入协调器的离线 v2 LIVE_HTTP dress rehearsal。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import httpx2
import pytest

from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, RepositoryState, canonical
from agentbench.deepseek_live_canary.cutover import execute_replacement_preflight
from tests.test_phase2b_ds1_r5 import TEST_HARNESS, ROOT, SYNTHETIC_KEY, TEST_SIGNING_KEY, signed_authorization

PREDECESSOR = "d92b541263edea9b749ff70f475fc4aad5b2fce0"


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    original = os._Environ.__getitem__
    def getitem(self, key):
        if key in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}: raise AssertionError("credential lookup")
        return original(self, key)
    def no_socket(*args, **kwargs): raise AssertionError("provider socket")
    monkeypatch.setattr(os._Environ, "__getitem__", getitem)
    monkeypatch.setattr(socket.socket, "connect", no_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)


def v2_authorization(tmp_path, *, key_id="r3-key", token_id="r3-token", run_id="r3-run", stage="PRECHECK_ONLY", kind="REPLACEMENT", mode="LIVE_HTTP", harness=TEST_HARNESS, issued=None, expires=None, ledger_path=None):
    now = int(time.time()); issued = now - 1 if issued is None else issued; expires = now + 300 if expires is None else expires
    private, public, message, signature = [tmp_path / name for name in ("private.pem", "public.pem", "intent.json", "signature.bin")]
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    intent={"schema_version":2,"stage":stage,"kind":kind,"run_id":run_id,"token_id":token_id,"harness_sha":harness,"approval_reference":"r3-offline-approval","transport_mode":mode,"predecessor_result_commit":PREDECESSOR,"key_id":key_id,"issued_at":issued,"expires_at":expires,"ledger_path":str((ledger_path or (tmp_path/"ledger.sqlite")).resolve())}
    message.write_text(canonical(intent),encoding="utf-8")
    subprocess.run(["openssl","dgst","-sha256","-sign",str(private),"-out",str(signature),str(message)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {"intent":intent,"signature":signature.read_bytes().hex()}, public.read_bytes()


def test_v2_live_positive_path_uses_real_coordinator_and_mock_transport(tmp_path):
    ledger=tmp_path/"ledger.sqlite"; auth, public=v2_authorization(tmp_path, ledger_path=ledger)
    callbacks=[]; factories=[]; seen=[]
    def handler(request):
        seen.append((request.method,request.url.path))
        return httpx2.Response(200,json={"data":[{"id":"deepseek-v4-pro"}]},request=request)
    def state_reader(_):
        return RepositoryState(TEST_HARNESS,TEST_HARNESS,"main",True,TEST_HARNESS,time.monotonic())
    def factory():
        factories.append(1)
        return httpx2.MockTransport(handler)
    outcome=execute_replacement_preflight(authorization=auth,verifier=AuthorizationVerifier(public_key_pem=public,key_id="r3-key"),ledger_path=ledger,output_dir=tmp_path/"evidence",repo_root=ROOT,run_id="r3-run",expected_harness_sha=TEST_HARNESS,credential_provider=lambda: callbacks.append(1) or SYNTHETIC_KEY,transport_factory=factory,state_reader=state_reader)
    assert outcome["status"]=="PASS" and outcome["ledger_state"]=="RESULT_PERSISTED"
    assert len(callbacks)==1 and len(factories)==1 and seen==[("GET","/models")]
    assert outcome["actual_external_network_calls"]==0 and outcome["canary_authorized"] is False


@pytest.mark.parametrize("mutate", [
    lambda intent: intent.update(stage="CANARY"), lambda intent: intent.update(kind="CANARY"),
    lambda intent: intent.update(transport_mode="MOCK_HTTP"), lambda intent: intent.update(run_id="other"),
    lambda intent: intent.update(token_id="other"), lambda intent: intent.update(harness_sha="b"*40),
    lambda intent: intent.update(key_id="other"), lambda intent: intent.update(issued_at=int(time.time())-10000),
])
def test_v2_invalid_intent_is_denied_before_credential_and_factory(tmp_path, mutate):
    ledger=tmp_path/"ledger.sqlite"; auth, public=v2_authorization(tmp_path, ledger_path=ledger)
    intent=auth["intent"].copy(); mutate(intent)
    # This intentionally does not re-sign the modified document.
    forged={"intent":intent,"signature":auth["signature"]}; callbacks=[]; factories=[]
    def factory(): factories.append(1); return httpx2.MockTransport(lambda request: httpx2.Response(200,json={"data":[]},request=request))
    with pytest.raises((ValueError,RuntimeError)):
        execute_replacement_preflight(authorization=forged,verifier=AuthorizationVerifier(public_key_pem=public,key_id="r3-key"),ledger_path=ledger,output_dir=tmp_path/"evidence",repo_root=ROOT,run_id="r3-run",expected_harness_sha=TEST_HARNESS,credential_provider=lambda: callbacks.append(1) or SYNTHETIC_KEY,transport_factory=factory,state_reader=lambda _: RepositoryState(TEST_HARNESS,TEST_HARNESS,"main",True,TEST_HARNESS,time.monotonic()))
    assert callbacks==[] and factories==[]


def test_legacy_v1_live_rejected_before_any_factory_or_credential(tmp_path):
    callbacks=[]; factories=[]
    with pytest.raises(ValueError):
        execute_replacement_preflight(authorization=signed_authorization(transport_mode="LIVE_HTTP"),verifier=AuthorizationVerifier(TEST_SIGNING_KEY),ledger_path=tmp_path/"ledger.sqlite",output_dir=tmp_path/"evidence",repo_root=ROOT,run_id="offline-r5-run",expected_harness_sha=TEST_HARNESS,credential_provider=lambda: callbacks.append(1) or SYNTHETIC_KEY,transport_factory=lambda: factories.append(1) or httpx2.MockTransport(lambda request: httpx2.Response(200,json={"data":[]},request=request)),state_reader=lambda _: RepositoryState(TEST_HARNESS,TEST_HARNESS,"main",True,TEST_HARNESS,time.monotonic()))
    assert callbacks==[] and factories==[]
