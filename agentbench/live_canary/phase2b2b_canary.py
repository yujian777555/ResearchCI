"""Phase 2B-2B：唯一 synthetic live canary runner。"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from openai import OpenAI

from agentbench.live_adapter.openai_responses import OpenAIResponsesAdapter, ResponsesRequestBuilder
from agentbench.live_runner.budget import BudgetConfig
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy
from agentbench.live_runner.trajectory import AppendOnlyTrajectory

ROOT = Path(__file__).resolve().parents[2]
CANARY_PATH = "CANARY.txt"
MARKER = "RESEARCHCI_CANARY_OK_2B2B"
TASK = (
    "This is a transport qualification task. Use the available read_file tool exactly once to read CANARY.txt. "
    "Do not call any other tool. After receiving the tool result, return a concise final text containing the exact marker from the file."
)


def _sha(value: Any) -> str:
    if isinstance(value, Path):
        data = value.read_bytes()
    elif isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _text_from_output(output: Any) -> str:
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"message", "output_text", "text"}:
            content = item.get("content", item.get("text", ""))
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        parts.append(part["text"])
                    elif hasattr(part, "text") and isinstance(part.text, str):
                        parts.append(part.text)
        elif isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


class RecordingLiveAdapter:
    """只记录本次 canary 的非敏感 provider response/request 证据。"""

    adapter_kind = "openai_live"
    is_live_provider = True

    def __init__(self, inner: OpenAIResponsesAdapter) -> None:
        self.inner = inner
        self.requests: list[dict[str, Any]] = []
        self.responses: list[Any] = []

    @property
    def provider_calls(self) -> int:
        return self.inner.provider_calls

    @property
    def fake_provider_calls(self) -> int:
        return self.inner.fake_provider_calls

    @property
    def live_api_calls(self) -> int:
        return self.inner.live_api_calls

    @property
    def network_calls(self) -> int:
        return self.inner.network_calls

    def create_response(self, request: dict[str, Any]):
        self.requests.append(deepcopy(request))
        response = self.inner.create_response(request)
        self.responses.append(response)
        return response


def main() -> int:
    key_present = bool(os.environ.get("OPENAI_API_KEY"))
    if not key_present:
        raise RuntimeError("OPENAI_API_KEY unavailable")

    fixture = ROOT / "agentbench" / "live_canary" / CANARY_PATH
    mediator_invocations: list[dict[str, Any]] = []

    def mediator(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        mediator_invocations.append({"tool": tool_name, "path": arguments.get("path")})
        if tool_name != "read_file" or arguments.get("path") != CANARY_PATH:
            return {"admitted": False, "decision": "REJECTED", "reason": "canary only permits read_file(CANARY.txt)"}
        return {"admitted": True, "path": CANARY_PATH, "content": fixture.read_text(encoding="utf-8")}

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    inner = OpenAIResponsesAdapter(client=client)
    adapter = RecordingLiveAdapter(inner)
    recorder = AppendOnlyTrajectory()
    request_builder = ResponsesRequestBuilder(ROOT)
    orchestrator = EpisodeOrchestrator(
        adapter=adapter,
        request_builder=request_builder,
        mediator=mediator,
        budget_config=BudgetConfig(max_steps=30, max_custom_function_calls=20, timeout_seconds=900, cumulative_output_token_budget=16000),
        retry_policy=RetryPolicy.from_file(ROOT / "agentbench/live_protocol/retry_policy.json"),
        recorder=recorder,
    )
    result = orchestrator.run(
        episode_id="phase2b2b-synthetic-canary-001",
        replicate_id=0,
        agent_visible_context=TASK,
        evaluator_private_metadata={"synthetic": True, "benchmark": False},
        execution_protocol="sha256:8c21a5a702bdb3b494457fe54c47261df9fdc6e4629149ad84353717219a030c",
    )

    provider_events = [event for event in result.events if event.get("event_type") == "provider_response"]
    request_events = [event for event in result.events if event.get("event_type") == "request"]
    call_events = [event for event in result.events if event.get("event_type") == "function_call"]
    retry_events = [event for event in result.events if event.get("event_type") in {"provider_error", "retry"}]
    final_text = _text_from_output(adapter.responses[-1].output) if adapter.responses else ""
    all_tool_names = [event.get("function_call", {}).get("name") for event in call_events]
    requested_paths = [event.get("tool_result", {}).get("mediator_result", {}).get("path") for event in call_events]
    first_response_id = provider_events[0].get("provider_response", {}).get("id") if provider_events else None
    continuation_previous = request_events[1].get("previous_response_id") if len(request_events) > 1 else None
    provider_call_id = call_events[0].get("function_call", {}).get("call_id") if call_events else None
    continuation_input = adapter.requests[1].get("input", []) if len(adapter.requests) > 1 else []
    continuation_call_id = continuation_input[0].get("call_id") if continuation_input else None
    credential_text = "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in result.events)
    credential_leakage = any(value in credential_text for value in ("OPENAI_API_KEY", "Bearer ", "Authorization:"))
    canary_pass = (
        len(request_events) >= 2
        and len(mediator_invocations) == 1
        and all_tool_names == ["read_file"]
        and requested_paths == [CANARY_PATH]
        and continuation_previous == first_response_id
        and continuation_call_id == provider_call_id
        and MARKER in final_text
        and result.termination_reason == "completed"
        and result.fake_provider_calls == 0
        and result.provider_calls == result.live_api_calls == result.network_calls
        and result.provider_calls > 0
        and not credential_leakage
    )
    report = {
        "phase": "2B-2B",
        "type": "synthetic_non_benchmark_live_canary",
        "canary_episodes": 1,
        "excluded_from_phase2c_metrics": True,
        "excluded_from_paper_efficacy_claims": True,
        "execution_protocol_hash": "sha256:8c21a5a702bdb3b494457fe54c47261df9fdc6e4629149ad84353717219a030c",
        "provider": "OpenAI",
        "endpoint": "/v1/responses",
        "model_requested": "gpt-5.6-sol",
        "provider_calls": result.provider_calls,
        "fake_provider_calls": result.fake_provider_calls,
        "live_api_calls": result.live_api_calls,
        "network_calls": result.network_calls,
        "termination_reason": result.termination_reason,
        "mediator_invocation_count": len(mediator_invocations),
        "previous_response_id_match": continuation_previous == first_response_id,
        "call_id_match": continuation_call_id == provider_call_id,
        "final_marker_present": MARKER in final_text,
        "final_text_sha256": _sha(final_text),
        "credential_leakage": credential_leakage,
        "status": "PASS" if canary_pass else "FAIL",
    }
    audit = {
        "phase": "2B-2B",
        "episode_id": result.episode_id,
        "execution_protocol_hash": report["execution_protocol_hash"],
        "model_requested": report["model_requested"],
        "request_events": [{"request_kind": e.get("request_kind"), "previous_response_id": e.get("previous_response_id"), "max_output_tokens": e.get("max_output_tokens"), "request_metadata_hash": e.get("request_metadata_hash")} for e in request_events],
        "responses": [e.get("provider_response") | {"usage": e.get("usage"), "budget_state": e.get("budget_state")} for e in provider_events],
        "function_calls": [{"call_id": e.get("function_call", {}).get("call_id"), "name": e.get("function_call", {}).get("name"), "arguments_hash": e.get("function_call", {}).get("arguments_hash")} for e in call_events],
        "mediator_invocations": mediator_invocations,
        "retry_events": retry_events,
        "accounting": result.as_dict() | {"events": None},
        "final_text_sha256": report["final_text_sha256"],
        "final_marker_present": report["final_marker_present"],
        "credential_leakage": credential_leakage,
        "benchmark_episodes": 0,
        "benchmark_scenarios_loaded": False,
    }
    reports = ROOT / "agentbench" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase2b2b_canary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (reports / "phase2b2b_live_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "provider_calls": report["provider_calls"], "live_api_calls": report["live_api_calls"], "network_calls": report["network_calls"], "mediator_invocation_count": report["mediator_invocation_count"], "final_marker_present": report["final_marker_present"], "termination_reason": report["termination_reason"]}, ensure_ascii=False))
    return 0 if canary_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
