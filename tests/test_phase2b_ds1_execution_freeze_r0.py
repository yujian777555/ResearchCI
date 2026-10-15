"""Execution freeze manifest 的离线 hard-stop 测试。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'agentbench/reports/phase2b_ds1_execution_freeze_r0.json'
SCOPE=ROOT/'agentbench/reports/phase2b_ds1_execution_freeze_r0_scope_audit.json'
FROZEN='52a643763a072bbc828e335d26f9e65d1ced8ab6'
EXPECTED_SCOPE={'method':'GET','endpoint':'/models','max_requests':1}


def load(): return json.loads(MANIFEST.read_text(encoding='utf-8'))


def hard_stop(item, *, head, action='validate'):
    if head != item['execution_sha']:
        return 'EXECUTION_INVALIDATED'
    if action == 'credential': return 'SECURITY_ABORT'
    if action == 'network_scope': return 'NETWORK_SCOPE_VIOLATION'
    if action == 'retry': return 'EXECUTION_ABORT'
    if item['scope'] != EXPECTED_SCOPE: return 'NETWORK_SCOPE_VIOLATION'
    if not item['artifact_binding']['all_repository_sha_match']: return 'CHAIN_INVALID'
    return 'READY_FOR_EXECUTION'


def test_freeze_sha_and_runtime_are_recorded():
    item=load()
    assert item['execution_sha']==FROZEN
    assert item['runtime']=='Linux WSL2 Ubuntu-22.04'
    assert item['provider']=='DeepSeek'


def test_current_manifest_preserves_chain_blocker():
    item=load()
    assert item['artifact_binding']['chain_status']=='CHAIN_INVALID'
    assert hard_stop(item, head=FROZEN)=='CHAIN_INVALID'


def test_head_mismatch_rejects_before_execution():
    assert hard_stop(load(), head='different-sha')=='EXECUTION_INVALIDATED'


def test_artifact_sha_mismatch_is_fail_closed():
    item=load(); item['artifact_binding']['all_repository_sha_match']=False
    assert hard_stop(item, head=FROZEN)=='CHAIN_INVALID'


def test_credential_violation_aborts_without_callback():
    assert hard_stop(load(), head=FROZEN, action='credential')=='SECURITY_ABORT'
    assert load()['hard_stop']['credential_callback_on_mismatch'] is False


def test_network_scope_violation_aborts():
    assert hard_stop(load(), head=FROZEN, action='network_scope')=='NETWORK_SCOPE_VIOLATION'
    assert hard_stop(load(), head=FROZEN, action='retry')=='EXECUTION_ABORT'


def test_positive_mocked_chain_is_ready_without_execution():
    item=load()
    item['artifact_binding']['all_repository_sha_match']=True
    item['artifact_binding']['chain_status']='VALID'
    assert hard_stop(item, head=FROZEN)=='READY_FOR_EXECUTION'
    assert all(value==0 for value in item['offline_counters'].values())


def test_offline_counters_and_scope_audit_are_zero_clean():
    item=load(); scope=json.loads(SCOPE.read_text(encoding='utf-8'))
    assert all(value==0 for value in item['offline_counters'].values())
    assert all(value==0 for value in scope['offline_counters'].values())
    assert scope['forbidden_changes_detected'] is False
