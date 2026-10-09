"""R2 独立离线安全测试；真实 link、属性模拟与未运行平台分别报告。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import time
from types import SimpleNamespace

import httpx2
import pytest

from agentbench.deepseek_live_canary import native_evidence as native
from agentbench.deepseek_live_canary import preflight
from agentbench.deepseek_live_canary.authorization import AuthorizationVerifier, RepositoryState, canonical
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog, QualificationGate, atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "a" * 40
RUN = "offline-r2"
TOKEN = "offline-r2-token"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = os._Environ.__getitem__
    def getitem(self, key):
        if key in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}:
            raise AssertionError("real credential lookup prohibited")
        return original(self, key)
    def no_network(*args, **kwargs): raise AssertionError("real provider network prohibited")
    monkeypatch.setattr(os._Environ, "__getitem__", getitem)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)


def test_existing_summary_is_explicitly_immutable(tmp_path):
    target = tmp_path / "summary.json"
    target.write_text('{"status":"FAIL_AUTH"}', encoding="utf-8")
    original = target.read_bytes()
    with pytest.raises(RuntimeError, match="already published"):
        atomic_write_json(target, {"status": "PASS"})
    assert target.read_bytes() == original


def test_predictable_temp_collision_independent_of_link_permission(tmp_path):
    temporary = tmp_path / "summary.json.tmp"
    temporary.write_bytes(b"do not truncate")
    with pytest.raises(RuntimeError, match="temporary"):
        atomic_write_json(tmp_path / "summary.json", {"status": "PASS"})
    assert temporary.read_bytes() == b"do not truncate"
    assert not (tmp_path / "summary.json").exists()


def test_qualification_uses_protected_summary_reader(tmp_path, monkeypatch):
    from tests.test_phase2b_ds1_r3 import _persisted_pass
    log, path, summary = _persisted_pass(tmp_path)
    reads = []
    original = preflight.native_read_text
    def deny_read(source, *args, **kwargs):
        if Path(source) != path:
            return original(source, *args, **kwargs)
        reads.append(1)
        raise RuntimeError("injected alias/identity failure")
    monkeypatch.setattr(preflight, "native_read_text", deny_read)
    gate = QualificationGate(audit_log=log, summary_path=path)
    assert gate.admit_preflight(summary) is False and reads
