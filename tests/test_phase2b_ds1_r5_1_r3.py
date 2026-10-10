from __future__ import annotations
import json, os, subprocess, socket, time
from pathlib import Path
import httpx2, pytest
from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, RepositoryState, canonical
from agentbench.deepseek_live_canary.cutover import execute_replacement_preflight
from tests.test_phase2b_ds1_r5 import TEST_HARNESS, ROOT, SYNTHETIC_KEY, signed_authorization, TEST_SIGNING_KEY
PREDECESSOR='d92b541263edea9b749ff70f475fc4aad5b2fce0'

@pytest.fixture(autouse=True)
def guard(monkeypatch):
    original=os._Environ.__getitem__
    def getitem(self,key):
        if key in {'DEEPSEEK_API_KEY','OPENAI_API_KEY'}: raise AssertionError('credential access')
        return original(self,key)
    def no_net(*a,**k): raise AssertionError('provider network')
    monkeypatch.setattr(os._Environ,'__getitem__',getitem); monkeypatch.setattr(socket.socket,'connect',no_net); monkeypatch.setattr(socket.socket,'connect_ex',no_net); monkeypatch.setattr(socket,'create_connection',no_net)

def keypair(tmp):
    tmp.mkdir(parents=True,exist_ok=True)
    priv,pub=tmp/'private.pem',tmp/'public.pem'
    subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(priv)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['openssl','pkey','-in',str(priv),'-pubout','-out',str(pub)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return priv,pub

def auth_for(tmp, **changes):
    priv,pub=keypair(tmp); now=int(time.time()); intent={'schema_version':2,'stage':'PRECHECK_ONLY','kind':'REPLACEMENT','run_id':'r3-1-run','token_id':'r3-1-token','harness_sha':TEST_HARNESS,'approval_reference':'r3-1-offline','transport_mode':'LIVE_HTTP','predecessor_result_commit':PREDECESSOR,'key_id':'r3-1-key','issued_at':now-1,'expires_at':now+300,'ledger_path':str((tmp/'ledger.sqlite').resolve())}; intent.update(changes); msg=tmp/'intent'; msg.write_text(canonical(intent),encoding='utf-8'); sig=tmp/'sig'; subprocess.run(['openssl','dgst','-sha256','-sign',str(priv),'-out',str(sig),str(msg)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return {'intent':intent,'signature':sig.read_bytes().hex()},pub.read_bytes()

def state(_): return RepositoryState(TEST_HARNESS,TEST_HARNESS,'main',True,TEST_HARNESS,time.monotonic())

def execute(tmp, auth, pub, *, verifier_key='r3-1-key', state_reader=state):
    cb=[]; factory=[]; requests=[]
    def handler(req): requests.append((req.method,req.url.path)); return httpx2.Response(200,json={'data':[{'id':'deepseek-v4-pro'}]},request=req)
    def factory_fn(): factory.append(1); return httpx2.MockTransport(handler)
    out=execute_replacement_preflight(authorization=auth,verifier=AuthorizationVerifier(public_key_pem=pub,key_id=verifier_key),ledger_path=tmp/'ledger.sqlite',output_dir=tmp/'evidence',repo_root=ROOT,run_id='r3-1-run',expected_harness_sha=TEST_HARNESS,credential_provider=lambda: cb.append(1) or SYNTHETIC_KEY,transport_factory=factory_fn,state_reader=state_reader)
    return out,cb,factory,requests

def test_signed_v2_live_positive_chain_and_no_post(tmp_path):
    auth,pub=auth_for(tmp_path); out,cb,factory,requests=execute(tmp_path,auth,pub); assert out['status']=='PASS' and out['ledger_state']=='RESULT_PERSISTED'; assert len(cb)==1 and len(factory)==1 and requests==[('GET','/models')]; assert out['canary_authorized'] is False

@pytest.mark.parametrize('change',[{'stage':'CANARY'},{'kind':'CANARY'},{'run_id':'other'},{'harness_sha':'b'*40},{'key_id':'other'},{'transport_mode':'MOCK_HTTP'},{'ledger_path':'C:/other.sqlite'},{'issued_at':'past'},{'issued_at':'future'}])
def test_resigned_policy_mismatches_reject_before_callback(tmp_path,change):
    if change.get('issued_at') == 'past': change={'issued_at':int(time.time())-10000}
    if change.get('issued_at') == 'future': change={'issued_at':int(time.time())+100}
    auth,pub=auth_for(tmp_path,**change); cb=[]; factory=[]
    def ff(): factory.append(1); return httpx2.MockTransport(lambda req: httpx2.Response(200,json={'data':[]},request=req))
    with pytest.raises((ValueError,RuntimeError)):
        execute_replacement_preflight(authorization=auth,verifier=AuthorizationVerifier(public_key_pem=pub,key_id='r3-1-key'),ledger_path=tmp_path/'ledger.sqlite',output_dir=tmp_path/'evidence',repo_root=ROOT,run_id='r3-1-run',expected_harness_sha=TEST_HARNESS,credential_provider=lambda: cb.append(1) or SYNTHETIC_KEY,transport_factory=ff,state_reader=state)
    assert cb==[] and factory==[]

def test_invalid_signature_revoked_key_token_and_v1_reject_before_callback(tmp_path):
    auth,pub=auth_for(tmp_path); bad=dict(auth,signature='00'*256); cb=[]; factory=[]
    with pytest.raises(ValueError): execute_replacement_preflight(authorization=bad,verifier=AuthorizationVerifier(public_key_pem=pub,key_id='r3-1-key'),ledger_path=tmp_path/'ledger.sqlite',output_dir=tmp_path/'bad',repo_root=ROOT,run_id='r3-1-run',expected_harness_sha=TEST_HARNESS,credential_provider=lambda: cb.append(1) or SYNTHETIC_KEY,transport_factory=lambda: factory.append(1) or httpx2.MockTransport(lambda req: None),state_reader=state)
    assert cb==[] and factory==[]
    auth2,pub2=auth_for(tmp_path/'revoked'); cb=[]; factory=[]
    with pytest.raises(ValueError): execute_replacement_preflight(authorization=auth2,verifier=AuthorizationVerifier(public_key_pem=pub2,key_id='r3-1-key',revoked_tokens={'r3-1-token'}),ledger_path=tmp_path/'revoked-ledger.sqlite',output_dir=tmp_path/'revoked-evidence',repo_root=ROOT,run_id='r3-1-run',expected_harness_sha=TEST_HARNESS,credential_provider=lambda: cb.append(1) or SYNTHETIC_KEY,transport_factory=lambda: factory.append(1) or httpx2.MockTransport(lambda req: None),state_reader=state)
    assert cb==[] and factory==[]
    with pytest.raises(ValueError): execute_replacement_preflight(authorization=signed_authorization(transport_mode='LIVE_HTTP'),verifier=AuthorizationVerifier(TEST_SIGNING_KEY),ledger_path=tmp_path/'v1.sqlite',output_dir=tmp_path/'v1-evidence',repo_root=ROOT,run_id='offline-r5-run',expected_harness_sha=TEST_HARNESS,credential_provider=lambda: cb.append(1) or SYNTHETIC_KEY,transport_factory=lambda: factory.append(1) or httpx2.MockTransport(lambda req: None),state_reader=state)
    assert cb==[] and factory==[]

def test_dirty_or_stale_repository_reject_before_callback_and_factory(tmp_path):
    auth,pub=auth_for(tmp_path); cb=[]; factory=[]
    bad=lambda _: RepositoryState('changed',TEST_HARNESS,'main',False,TEST_HARNESS,time.monotonic())
    with pytest.raises(RuntimeError): execute_replacement_preflight(authorization=auth,verifier=AuthorizationVerifier(public_key_pem=pub,key_id='r3-1-key'),ledger_path=tmp_path/'ledger.sqlite',output_dir=tmp_path/'evidence',repo_root=ROOT,run_id='r3-1-run',expected_harness_sha=TEST_HARNESS,credential_provider=lambda: cb.append(1) or SYNTHETIC_KEY,transport_factory=lambda: factory.append(1) or httpx2.MockTransport(lambda req: None),state_reader=bad)
    assert cb==[] and factory==[]
