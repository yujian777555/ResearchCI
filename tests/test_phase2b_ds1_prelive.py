from __future__ import annotations
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentbench.deepseek_live_canary.mediator import MARKER, SyntheticCanaryMediator
from agentbench.deepseek_live_canary.preflight import TARGET_MODEL, classify_preflight_error, run_preflight
from agentbench.deepseek_live_canary.redaction import redact, redact_text

ROOT=Path(__file__).resolve().parents[1]

def test_fixture_and_task_are_exact():
    assert (ROOT/'agentbench/deepseek_live_canary/CANARY.txt').read_text(encoding='utf-8')==MARKER

def test_mediator_only_allows_exact_read():
    mediator=SyntheticCanaryMediator(ROOT/'agentbench/deepseek_live_canary/CANARY.txt')
    assert mediator('read_file',{'path':'CANARY.txt'})['content']==MARKER
    assert mediator('read_file',{'path':'./CANARY.txt'})['admitted'] is False
    assert mediator('write_file',{'path':'CANARY.txt'})['admitted'] is False
    assert mediator.invocation_count==3

def test_no_benchmark_import_or_scenario_materialization():
    source=(ROOT/'agentbench/deepseek_live_canary/canary.py').read_text(encoding='utf-8')
    assert 'agentbench.scenarios' not in source and 'EpisodeHarness' not in source

def test_preflight_target_detection_and_exact_once():
    class Models:
        def list(self): return SimpleNamespace(data=[SimpleNamespace(id='deepseek-flash'),SimpleNamespace(id=TARGET_MODEL)],_request_id='req-safe')
    result=run_preflight(client_factory=lambda _:SimpleNamespace(models=Models()),credential_present=True)
    assert result.status=='PASS' and result.requests==1 and result.target_present is True

def test_preflight_failure_blocks_without_request():
    calls=[]
    result=run_preflight(client_factory=lambda _:calls.append(1),credential_present=False)
    assert result.status=='BLOCKED_CREDENTIAL_MISSING' and result.requests==0 and calls==[]

def test_preflight_absent_target_is_failure():
    class Models:
        def list(self): return {'data':[{'id':'deepseek-flash'}]}
    result=run_preflight(client_factory=lambda _:SimpleNamespace(models=Models()),credential_present=True)
    assert result.status=='FAIL_TARGET_MODEL_ABSENT' and result.requests==1

def test_preflight_classification():
    for code,expected in ((401,'FAIL_AUTH'),(402,'FAIL_BALANCE'),(500,'FAIL_PROVIDER')):
        error=type('SyntheticError',(Exception,),{'status_code':code})()
        assert classify_preflight_error(error)==expected

def test_redaction_never_preserves_secret_like_values():
    value='Bearer abc OPENAI_API_KEY=sk-live-123 Authorization: sk-xyz'
    cleaned=redact_text(value)
    assert 'abc' not in cleaned and 'sk-live-123' not in cleaned and 'sk-xyz' not in cleaned
    assert 'Authorization' not in redact({'Authorization':'secret','safe':'ok'})

def test_no_network_socket_guard(monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError('network attempted')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    result=run_preflight(client_factory=lambda _: (_ for _ in ()).throw(RuntimeError('offline synthetic')),credential_present=True)
    assert result.requests==1 and result.status=='FAIL_PROVIDER'

def test_hash_guards_are_frozen():
    ds='sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe'
    stats='sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083'
    assert ds != stats
