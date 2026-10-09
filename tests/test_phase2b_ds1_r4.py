"""R4：安装的 SDK、内存 HTTP 传输和冻结执行链的行为级验收。"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import socket

import httpx2
import pytest
from openai.types.responses import Response

from agentbench.deepseek_adapter.deepseek_responses import DeepSeekRequestBuilder, DeepSeekResponsesAdapter
from agentbench.deepseek_live_canary.canary import TASK, run_canary
from agentbench.deepseek_live_canary.mediator import MARKER
from agentbench.deepseek_live_canary.preflight import PreflightAuditLog, build_audited_models_client
from agentbench.deepseek_live_canary.preflight import QualificationGate, persist_preflight_result, run_preflight
from agentbench.live_adapter.errors import ProviderError

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_KEY = "researchci-r4-synthetic-credential"


@pytest.fixture(autouse=True)
def forbid_external_network_and_real_key_reads(monkeypatch):
    def forbidden_network(*args, **kwargs):
        raise AssertionError("R4 禁止外部网络访问")
    original = os._Environ.__getitem__
    def guarded_getitem(self, key):
        if key in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}:
            raise AssertionError("R4 禁止读取真实 API Key")
        return original(self, key)
    monkeypatch.setattr(os._Environ, "__getitem__", guarded_getitem)
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)


def wire_response(number, output, *, output_tokens=11, status="completed", model="deepseek-v4-pro"):
    return {"id": f"resp_offline_{number}", "object": "response", "created_at": 1800000000,
            "status": status, "error": None, "incomplete_details": None, "model": model,
            "output": output, "usage": {"input_tokens": 7, "output_tokens": output_tokens,
                "total_tokens": 7 + output_tokens, "input_tokens_details": {"cached_tokens": 2},
                "output_tokens_details": {"reasoning_tokens": 3}}}


def tool_turn():
    return wire_response(1, [
        {"id": "rs_offline", "type": "reasoning", "summary": [], "status": "completed",
         "content": [{"type": "reasoning_text", "text": "synthetic reasoning"}]},
        {"id": "fc_offline", "type": "function_call", "status": "completed", "call_id": "exact_call_id_r4",
         "name": "read_file", "arguments": '{"path":"CANARY.txt"}'},
    ])


def final_turn():
    return wire_response(2, [{"id": "msg_offline", "type": "message", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text", "text": MARKER, "annotations": []}]}], output_tokens=5)


def sdk_fixture(tmp_path, sequence):
    log = PreflightAuditLog(tmp_path / "primary.jsonl")
    seen = []
    items = iter(deepcopy(sequence))
    def handler(request):
        # SDK 序列化后的实际 wire JSON 只保存在内存中。
        seen.append({"method": request.method, "path": request.url.path,
                     "body": json.loads(request.content) if request.content else None})
        item = next(items)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            return httpx2.Response(item, json={"error": {"message": "synthetic error"}}, request=request)
        if item == "__malformed__":
            return httpx2.Response(200, content=b"not-json", request=request)
        return httpx2.Response(200, json=item, headers={"x-request-id": "offline-request"}, request=request)
    client, audit = build_audited_models_client(api_key=SYNTHETIC_KEY, audit_log=log, transport=httpx2.MockTransport(handler))
    return client, audit, log, seen


def test_factory_has_explicit_frozen_timeout_and_separate_wire_counters(tmp_path):
    client, audit, _, _ = sdk_fixture(tmp_path, [])
    try:
        assert client.max_retries == 0
        assert client.timeout.read == 900 and client.timeout.connect <= 900
        assert audit.attempts_by_endpoint == {"models": 0, "responses": 0}
    finally:
        client.close()


def test_actual_sdk_two_turn_canary_labels_mock_wire_and_inspects_serialization(tmp_path):
    client, audit, _, seen = sdk_fixture(tmp_path, [tool_turn(), final_turn()])
    try:
        outcome = run_canary(root=ROOT, adapter=DeepSeekResponsesAdapter(client=client), sleep=lambda _: None)
    finally:
        client.close()
    assert outcome["status"] == "PASS"
    assert outcome["adapter_mode"] == "SIMULATED_LIVE_ADAPTER_OFFLINE"
    assert outcome["actual_external_network_calls"] == 0
    assert len(seen) == 2 and [request["path"] for request in seen] == ["/responses", "/responses"]
    builder = DeepSeekRequestBuilder(ROOT)
    first, second = [request["body"] for request in seen]
    for body in (first, second):
        assert set(body) == set(builder.contract["request_allowlist"])
        assert body["model"] == "deepseek-v4-pro" and body["reasoning"] == {"effort": "max"}
        assert body["top_p"] == 0.95 and body["tools"] == builder.tools
        assert body["instructions"] == builder.system_prompt
    assert first["max_output_tokens"] == 16000 and second["max_output_tokens"] == 15989
    assert first["input"] == [{"type": "message", "role": "user", "content": TASK}]
    assert [item["type"] for item in second["input"]] == ["message", "reasoning", "function_call", "function_call_output"]
    assert second["input"][2]["call_id"] == second["input"][3]["call_id"] == "exact_call_id_r4"
    assert audit.attempts_by_endpoint == {"models": 0, "responses": 2}


@pytest.mark.parametrize("kind,expected,present", [
    ("present", "PASS", True), ("absent", "FAIL_TARGET_MODEL_ABSENT", False),
    (401, "FAIL_AUTH", None), (402, "FAIL_BALANCE", None), (429, "FAIL_PROVIDER", None),
    (500, "FAIL_PROVIDER", None), (503, "FAIL_PROVIDER", None),
    ("timeout", "FAIL_NETWORK", None), ("connection", "FAIL_NETWORK", None),
    ("malformed", "FAIL_PROVIDER", None),
])
def test_sdk_models_single_attempt_outcome_persistence(tmp_path, kind, expected, present):
    if kind in {"present", "absent"}:
        item = {"data": [{"id": "deepseek-v4-pro" if kind == "present" else "other"}]}
    elif kind == "timeout": item = httpx2.ReadTimeout("synthetic")
    elif kind == "connection": item = httpx2.ConnectError("synthetic")
    elif kind == "malformed": item = "__malformed__"
    else: item = kind
    client, audit, log, seen = sdk_fixture(tmp_path, [item])
    try:
        result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
        summary = persist_preflight_result(result, tmp_path / "summary.json", log)
    finally: client.close()
    assert result.status == expected and result.target_present is present
    assert summary["provider_outcome_persisted"] is True
    assert len(seen) == result.sdk_invocations == result.http_attempts_observed == 1
    assert audit.sdk_invocations_by_endpoint == audit.attempts_by_endpoint == {"models": 1, "responses": 0}
    events = log.events()
    assert [e["event"] for e in events[:3]] == ["preflight_start", "sdk_invocation", "transport_attempt"]
    assert events[-1]["event"] == "preflight_outcome_persisted"
    gate = QualificationGate(audit_log=log, summary_path=tmp_path / "summary.json")
    assert gate.admit_preflight(summary)
    assert gate.admit_canary(summary) is (kind == "present")


@pytest.mark.parametrize("kind,expected,retryable", [
    (400, "InvalidRequestError", False), (401, "AuthenticationError", False),
    (402, "InsufficientBalanceError", False), (422, "InvalidRequestError", False),
    (429, "RateLimitError", True), (500, "TransientProviderError", True),
    (503, "TransientProviderError", True), ("timeout", "TimeoutError", True),
    ("connection", "ConnectionError", True),
])
def test_sdk_responses_error_mapping_has_no_hidden_retries(tmp_path, kind, expected, retryable):
    item = httpx2.ReadTimeout("synthetic") if kind == "timeout" else httpx2.ConnectError("synthetic") if kind == "connection" else kind
    client, audit, log, seen = sdk_fixture(tmp_path, [item])
    builder = DeepSeekRequestBuilder(ROOT)
    try:
        with pytest.raises(ProviderError) as caught:
            DeepSeekResponsesAdapter(client=client).create_response(builder.build(
                agent_visible_context=builder.initial_history(TASK), replicate_id=0, remaining_output_token_budget=16000))
    finally: client.close()
    assert caught.value.error_type == expected and caught.value.retryable is retryable
    assert audit.attempts_by_endpoint == {"models": 0, "responses": 1}
    assert audit.sdk_invocations_by_endpoint == {"models": 0, "responses": 1} and len(seen) == 1
    assert log.events()[0]["event"] == "sdk_call_start"


@pytest.mark.parametrize("kind", ["no_tool", "wrong_tool", "wrong_path", "duplicate", "invalid_args",
                                   "missing_marker", "empty", "refusal", "malformed", "incomplete", "wrong_model"])
def test_sdk_canary_negative_behavior_fails_closed(tmp_path, kind):
    first, last = tool_turn(), final_turn()
    if kind == "no_tool": first = final_turn()
    if kind == "wrong_tool": first["output"][1]["name"] = "not_a_tool"
    if kind == "wrong_path": first["output"][1]["arguments"] = '{"path":"other.txt"}'
    if kind == "duplicate": first["output"].append(dict(first["output"][1], call_id="second"))
    if kind == "invalid_args": first["output"][1]["arguments"] = "bad-json"
    if kind == "missing_marker": last["output"][0]["content"][0]["text"] = "no marker"
    if kind == "empty": last["output"][0]["content"] = []
    if kind == "refusal": last["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
    if kind == "malformed": last["output"] = []
    if kind == "incomplete": last["status"] = "incomplete"
    if kind == "wrong_model": last["model"] = "other-model"
    client, _, _, _ = sdk_fixture(tmp_path, [first, last])
    try: outcome = run_canary(root=ROOT, adapter=DeepSeekResponsesAdapter(client=client), sleep=lambda _: None)
    finally: client.close()
    assert outcome["status"] == "FAIL"


def test_real_sdk_decode_keeps_pydantic_item_shapes_and_usage(tmp_path):
    client, _, _, _ = sdk_fixture(tmp_path, [tool_turn()])
    builder = DeepSeekRequestBuilder(ROOT)
    try:
        raw = client.responses.create(**builder.build(agent_visible_context=builder.initial_history(TASK),
            replicate_id=0, remaining_output_token_budget=16000))
        assert isinstance(raw, Response)
        decoded = DeepSeekResponsesAdapter.parse_response(raw)
    finally: client.close()
    assert decoded.output[0]["content"][0]["text"] == "synthetic reasoning"
    assert decoded.output[1]["call_id"] == "exact_call_id_r4"
    assert decoded.usage == {"input_tokens": 7, "output_tokens": 11, "total_tokens": 18}
    assert decoded.usage_details["output_tokens_details"]["reasoning_tokens"] == 3


@pytest.mark.parametrize("errors", [[429, 503], [500, 503], [httpx2.ReadTimeout("synthetic"), httpx2.ConnectError("synthetic")]])
def test_sdk_outer_retry_keeps_replay_budgets_and_single_tool(tmp_path, errors):
    client, audit, _, seen = sdk_fixture(tmp_path, [tool_turn(), *errors, final_turn()])
    sleeps = []
    try: outcome = run_canary(root=ROOT, adapter=DeepSeekResponsesAdapter(client=client), sleep=sleeps.append)
    finally: client.close()
    assert outcome["status"] == "PASS" and outcome["mediator_invocation_count"] == 1
    assert sleeps == [1.0, 2.0] and outcome["provider_calls"] == 4
    assert audit.attempts_by_endpoint["responses"] == audit.sdk_invocations_by_endpoint["responses"] == 4
    assert seen[1]["body"] == seen[2]["body"] == seen[3]["body"]
    assert seen[3]["body"]["max_output_tokens"] == 15989
    terminal = outcome["events"][-1]["budget_state"]
    assert terminal["executed_steps"] == 2 and terminal["executed_custom_function_calls"] == 1
    assert terminal["cumulative_output_tokens"] == 16


def test_summary_crash_and_process_interruption_preserve_evidence_and_block_restart(tmp_path, monkeypatch):
    client, _, log, seen = sdk_fixture(tmp_path, [{"data": [{"id": "deepseek-v4-pro"}]}])
    try: result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    finally: client.close()
    import agentbench.deepseek_live_canary.preflight as module
    monkeypatch.setattr(module, "serialize_preflight_summary", lambda _: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError): persist_preflight_result(result, tmp_path / "summary.json", log)
    assert any(e["event"] == "preflight_outcome_persisted" for e in log.events())
    assert not QualificationGate(audit_log=log, summary_path=tmp_path / "summary.json").admit_preflight({"status": "PASS"})
    with pytest.raises(RuntimeError): run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    assert len(seen) == 1


def test_terminal_systemexit_cannot_restart_same_run(tmp_path):
    client, _, log, seen = sdk_fixture(tmp_path, [SystemExit(19)])
    try:
        with pytest.raises(SystemExit): run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
        with pytest.raises(RuntimeError): run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    finally: client.close()
    assert len(seen) == 1 and any(e["event"] == "transport_error" for e in log.events())
