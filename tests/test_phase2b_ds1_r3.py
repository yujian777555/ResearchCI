"""Phase 2B-DS-1-R3 真实 SDK 构造链的离线行为验收。"""
from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

from agentbench.deepseek_adapter.deepseek_responses import DeepSeekResponsesAdapter
from agentbench.deepseek_live_canary.canary import run_canary
from agentbench.deepseek_live_canary.cli import main, offline_selftest
from agentbench.deepseek_live_canary.preflight import (
    PreflightAuditLog,
    QualificationGate,
    TransportAudit,
    build_audited_models_client,
    persist_preflight_result,
    run_preflight,
)
from agentbench.live_adapter.types import ProviderResponse

ROOT = Path(__file__).resolve().parents[1]


def _response(response_id: str, output: list[dict]) -> ProviderResponse:
    return ProviderResponse(response_id, "deepseek-v4-pro", 1, tuple(output), {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})


def _sequence() -> list[ProviderResponse]:
    return [
        _response("r1", [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "offline"}]}, {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": '{"path":"CANARY.txt"}'}]),
        _response("r2", [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "RESEARCHCI_DEEPSEEK_CANARY_OK_DS1"}]}]),
    ]


def _simulated_adapter():
    responses = iter(_sequence())
    return DeepSeekResponsesAdapter(transport=lambda _request: next(responses))


def _sdk_preflight(tmp_path, handler):
    log = PreflightAuditLog(tmp_path / "primary.jsonl")
    client, audit = build_audited_models_client(api_key="offline-synthetic-key", audit_log=log, transport=httpx2.MockTransport(handler))
    result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    client.close()
    return result, audit, log


def test_real_sdk_models_list_uses_instrumented_mocktransport_once(tmp_path):
    seen = []
    def handler(request):
        seen.append((request.method, str(request.url)))
        return httpx2.Response(200, json={"data": [{"id": "deepseek-v4-pro"}]}, request=request)
    result, audit, log = _sdk_preflight(tmp_path, handler)
    assert result.status == "PASS"
    assert result.sdk_invocations == 1 and result.http_attempts_observed == 1 and result.responses_http_attempts_observed == 1
    assert result.http_attempt_count_verified is True and audit.max_retries == 0
    assert seen == [("GET", "https://api.deepseek.com/models")]
    assert [event["event"] for event in log.events()[:4]] == ["preflight_start", "sdk_invocation", "transport_attempt", "transport_response"]


@pytest.mark.parametrize("kind", ["absent", "401", "429", "503", "timeout", "malformed"])
def test_real_sdk_mocktransport_failure_matrix_is_single_attempt_and_fail_closed(tmp_path, kind):
    calls = []
    def handler(request):
        calls.append(request)
        if kind == "absent":
            return httpx2.Response(200, json={"data": [{"id": "deepseek-flash"}]}, request=request)
        if kind == "malformed":
            return httpx2.Response(200, content=b"not-json", request=request)
        if kind == "timeout":
            raise httpx2.ReadTimeout("offline timeout", request=request)
        return httpx2.Response(int(kind), json={"error": {"message": "offline synthetic"}}, request=request)
    result, audit, log = _sdk_preflight(tmp_path, handler)
    assert len(calls) == 1 and audit.http_attempts == 1 and audit.max_retries == 0
    assert result.status != "PASS"
    assert result.sdk_invocations == 1
    events = log.events()
    assert any(event["event"] in {"transport_response", "transport_error"} for event in events)


def test_actual_sdk_result_survives_derived_summary_crash(tmp_path, monkeypatch):
    def handler(request):
        return httpx2.Response(200, json={"data": [{"id": "deepseek-v4-pro"}]}, request=request)
    result, _audit, log = _sdk_preflight(tmp_path, handler)
    import agentbench.deepseek_live_canary.preflight as module
    monkeypatch.setattr(module, "serialize_preflight_summary", lambda _: (_ for _ in ()).throw(RuntimeError("offline derived crash")))
    with pytest.raises(RuntimeError):
        persist_preflight_result(result, tmp_path / "summary.json", log)
    assert any(event["event"] == "preflight_outcome_persisted" for event in log.events())


def test_fake_and_simulated_live_canary_share_behavior_gate():
    from agentbench.deepseek_adapter.fake_provider import FakeDeepSeekResponsesAdapter
    fake = run_canary(root=ROOT, adapter=FakeDeepSeekResponsesAdapter(_sequence()), sleep=lambda _: None)
    simulated = run_canary(root=ROOT, adapter=_simulated_adapter(), sleep=lambda _: None)
    assert fake["status"] == simulated["status"] == "PASS"
    assert fake["adapter_mode"] == "FAKE_ADAPTER_OFFLINE"
    assert simulated["adapter_mode"] == "SIMULATED_LIVE_ADAPTER_OFFLINE"
    assert fake["fake_provider_calls"] == 2 and fake["live_api_calls"] == 0 and fake["network_calls"] == 0
    assert simulated["fake_provider_calls"] == 0 and simulated["live_api_calls"] == 2 and simulated["network_calls"] == 2 and simulated["actual_external_network_calls"] == 0
    assert fake["successful_response_count"] == simulated["successful_response_count"] == 2


def test_simulated_live_replay_audit_does_not_use_fake_requests():
    adapter = _simulated_adapter()
    outcome = run_canary(root=ROOT, adapter=adapter, sleep=lambda _: None)
    assert outcome["status"] == "PASS" and outcome["replay_valid"] is True
    assert outcome["replay_audit"]["initial_task_valid"] is True
    assert outcome["replay_audit"]["call_id_preserved"] is True
    assert outcome["replay_audit"]["forbidden_fields"] is False
    assert not hasattr(adapter, "requests")


def test_tampered_simulated_replay_fails_closed():
    from agentbench.deepseek_live_canary.observation import ObservationalResponsesAdapter
    class TamperedAdapter(ObservationalResponsesAdapter):
        def create_response(self, request):
            if not self._request_snapshots:
                request["input"][-1]["call_id"] = "tampered"
            return super().create_response(request)
    responses = iter(_sequence())
    outcome = run_canary(root=ROOT, adapter=TamperedAdapter(DeepSeekResponsesAdapter(transport=lambda _request: next(responses))), sleep=lambda _: None)
    assert outcome["status"] == "FAIL" and outcome["replay_valid"] is False


def _persisted_pass(tmp_path):
    log = PreflightAuditLog(tmp_path / "primary.jsonl")
    from agentbench.deepseek_live_canary.preflight import OfflineModelListClient
    client = OfflineModelListClient(TransportAudit(), response={"data": [{"id": "deepseek-v4-pro"}]})
    result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    summary_path = tmp_path / "summary.json"
    summary = persist_preflight_result(result, summary_path, log)
    return log, summary_path, summary


def test_persisted_pass_gate_rejection_matrix(tmp_path):
    log, summary_path, summary = _persisted_pass(tmp_path / "valid")
    gate = QualificationGate(audit_log=log, summary_path=summary_path)
    assert gate.admit_preflight(summary) and gate.admit_canary(summary)
    restarted = QualificationGate(audit_log=log, summary_path=summary_path)
    assert not restarted.admit_preflight(summary)

    forged = QualificationGate()
    assert not forged.admit_preflight({"status": "PASS", "target_present": True, "http_attempts_observed": 1, "http_attempt_count_verified": True, "provider_outcome_persisted": True})

    tamper_dir = tmp_path / "tampered"
    tamper_log, tamper_summary_path, tamper_summary = _persisted_pass(tamper_dir)
    tamper_summary_path.write_text(json.dumps(dict(tamper_summary, status="PASS", target_present=False)), encoding="utf-8")
    assert not QualificationGate(audit_log=tamper_log, summary_path=tamper_summary_path).admit_preflight(tamper_summary)

    duplicate_dir = tmp_path / "duplicate"
    duplicate_log, duplicate_summary_path, duplicate_summary = _persisted_pass(duplicate_dir)
    duplicate_log.append({"event": "preflight_outcome_persisted", "status": "PASS", "target_present": True, "provider_outcome_observed": True, "provider_outcome_persisted": True, "http_attempts_observed": 1, "http_attempt_count_verified": True})
    assert not QualificationGate(audit_log=duplicate_log, summary_path=duplicate_summary_path).admit_preflight(duplicate_summary)


def test_cli_offline_selftest_runs_fake_and_simulated_live_and_remains_disabled():
    assert offline_selftest() == 0
    assert offline_selftest(corrupt=True) != 0
    assert main(["preflight"]) == 2 and main(["canary"]) == 2

