"""Phase 2B-DS-1-R2 离线行为级验收。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.deepseek_adapter import FakeDeepSeekResponsesAdapter
from agentbench.deepseek_live_canary.canary import TASK, extract_assistant_output_text, run_canary
from agentbench.deepseek_live_canary.cli import main, offline_selftest
from agentbench.deepseek_live_canary.mediator import MARKER
from agentbench.deepseek_live_canary.preflight import (
    OfflineModelListClient,
    PreflightAuditLog,
    QualificationGate,
    TransportAudit,
    canary_eligibility,
    persist_preflight_result,
    run_preflight,
)
from agentbench.live_adapter.errors import ProviderError
from agentbench.live_adapter.types import ProviderResponse

ROOT = Path(__file__).resolve().parents[1]


def response(response_id: str, output: list[dict]) -> ProviderResponse:
    return ProviderResponse(response_id, "deepseek-v4-pro", 1, tuple(output), {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})


def reasoning() -> dict:
    return {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "offline"}]}


def call(call_id: str = "call_1", path: str = "CANARY.txt") -> dict:
    return {"type": "function_call", "call_id": call_id, "name": "read_file", "arguments": json.dumps({"path": path})}


def message(text: str = MARKER) -> dict:
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def valid_adapter(*, final: str = MARKER, first_call: dict | None = None):
    return FakeDeepSeekResponsesAdapter([
        response("r1", [reasoning(), first_call or call()]),
        response("r2", [message(final)]),
    ])


def test_transport_audit_separates_sdk_invocation_from_wire_attempt_and_disables_retry(tmp_path):
    audit = TransportAudit(max_retries=0)
    client = OfflineModelListClient(audit, error=type("RetryableHttp503", (Exception,), {"status_code": 503})())
    log = PreflightAuditLog(tmp_path / "primary.jsonl")
    result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    assert result.requests == 1
    assert result.http_attempts_observed == 1
    assert result.responses_http_attempts_observed == 0
    assert result.http_attempt_count_verified is False
    assert audit.max_retries == 0 and audit.http_attempts == 1
    events = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events[:4]] == ["preflight_start", "sdk_invocation", "transport_attempt", "transport_error"]
    assert not any(event.get("attempt_index") == 2 for event in events)


def test_primary_outcome_survives_derived_serializer_crash(tmp_path, monkeypatch):
    audit = TransportAudit()
    client = OfflineModelListClient(audit, response={"data": [{"id": "deepseek-v4-pro"}]})
    log = PreflightAuditLog(tmp_path / "primary.jsonl")
    result = run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    import agentbench.deepseek_live_canary.preflight as module
    monkeypatch.setattr(module, "serialize_preflight_summary", lambda _: (_ for _ in ()).throw(RuntimeError("derived serializer crash")))
    with pytest.raises(RuntimeError):
        persist_preflight_result(result, tmp_path / "summary.json", log)
    text = log.path.read_text(encoding="utf-8")
    assert '"event":"preflight_outcome_persisted"' in text
    assert not (tmp_path / "summary.json").exists()


def test_primary_audit_allowlist_and_redaction(tmp_path):
    log = PreflightAuditLog(tmp_path / "primary.jsonl")
    log.append({"event": "synthetic", "Authorization": "Bearer sk-secret", "error_class": "Bearer sk-secret", "headers": {"Authorization": "sk-secret"}, "safe": "dropped"})
    text = log.path.read_text(encoding="utf-8")
    assert "sk-secret" not in text and "Authorization" not in text and "headers" not in text


def test_canary_gate_requires_durable_verified_pass_and_is_single_use():
    gate = QualificationGate()
    evidence = {"status": "PASS", "target_present": True, "http_attempts_observed": 1, "http_attempt_count_verified": True, "provider_outcome_persisted": True}
    assert gate.admit_preflight(evidence)
    assert gate.admit_canary(evidence)
    assert not gate.admit_canary(evidence)
    unpersisted_gate = QualificationGate()
    unpersisted = dict(evidence, provider_outcome_persisted=False)
    assert unpersisted_gate.admit_preflight(unpersisted)
    assert not unpersisted_gate.admit_canary(unpersisted)
    failed_gate = QualificationGate()
    assert failed_gate.admit_preflight({"status": "FAIL_PROVIDER"})
    assert not failed_gate.admit_preflight({"status": "PASS"})
    assert not failed_gate.admit_canary(evidence)
    assert not canary_eligibility({"status": "PASS", "target_present": None, "http_attempts_observed": 1, "http_attempt_count_verified": True, "provider_outcome_persisted": True})


def test_output_text_extractor_is_typed_and_fail_closed():
    assert extract_assistant_output_text([message("a"), message("b")]) == "ab"
    assert extract_assistant_output_text([{"type": "message", "content": "[{'type':'output_text'}]"}]) is None
    assert extract_assistant_output_text([{"type": "message", "content": [{"type": "refusal", "text": "no"}]}]) is None
    assert extract_assistant_output_text([{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "r"}]}]) is None


def test_full_fake_two_turn_canary_passes_with_exact_replay_and_accounting():
    adapter = valid_adapter()
    outcome = run_canary(root=ROOT, adapter=adapter, sleep=lambda _: None)
    assert outcome["status"] == "PASS"
    assert outcome["function_call_count"] == 1
    assert outcome["mediator_invocation_count"] == 1
    assert outcome["call_id_valid"] and outcome["replay_valid"]
    assert outcome["marker_present"] and outcome["termination_reason"] == "completed"
    assert outcome["fake_provider_calls"] == 2 and outcome["live_api_calls"] == 0 and outcome["network_calls"] == 0


@pytest.mark.parametrize("adapter", [
    valid_adapter(first_call=call(path="wrong.txt")),
    FakeDeepSeekResponsesAdapter([response("r1", [reasoning(), call("a"), call("b")]), response("r2", [message()])]),
    FakeDeepSeekResponsesAdapter([response("r1", [message(MARKER)])]),
    valid_adapter(final="no marker"),
    FakeDeepSeekResponsesAdapter([response("r1", [reasoning(), call()]), response("r2", [{"type": "message", "content": [{"type": "refusal", "text": "bad"}]}])]),
])
def test_illegal_canary_branches_fail_closed(adapter):
    assert run_canary(root=ROOT, adapter=adapter, sleep=lambda _: None)["status"] == "FAIL"


def test_retry_backoff_is_observed_in_full_fake_orchestrator():
    adapter = FakeDeepSeekResponsesAdapter([
        ProviderError("temporary", error_type="RateLimitError", retryable=True),
        response("r1", [reasoning(), call()]),
        response("r2", [message()]),
    ])
    sleeps: list[float] = []
    outcome = run_canary(root=ROOT, adapter=adapter, sleep=sleeps.append)
    assert outcome["status"] == "PASS"
    assert sleeps == [1.0]
    assert outcome["mediator_invocation_count"] == 1 and outcome["fake_provider_calls"] == 3


def test_cli_selftest_is_real_and_corruption_fails_without_live_modes():
    assert offline_selftest() == 0
    assert offline_selftest(corrupt=True) != 0
    assert main(["preflight"]) == 2 and main(["canary"]) == 2


def test_task_uses_frozen_backticks_and_no_benchmark_import():
    frozen = next(line[2:] for line in (ROOT / "docs/PHASE2B_DS1_PLAN.md").read_text(encoding="utf-8").splitlines() if line.startswith("> This is a transport qualification task."))
    assert TASK == frozen
    assert "agentbench.scenarios" not in (ROOT / "agentbench/deepseek_live_canary/canary.py").read_text(encoding="utf-8")
