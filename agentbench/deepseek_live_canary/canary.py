"""DS-1 canary orchestration glue; no benchmark imports."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any
from agentbench.deepseek_adapter.deepseek_responses import DeepSeekRequestBuilder, DeepSeekResponsesAdapter
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy
from agentbench.live_runner.budget import BudgetConfig
from agentbench.live_runner.trajectory import AppendOnlyTrajectory
from .mediator import SyntheticCanaryMediator, MARKER
from .observation import ObservationalResponsesAdapter, classify_adapter_mode

TASK="This is a transport qualification task. Use the available `read_file` tool exactly once to read `CANARY.txt`. Do not call any other tool. After receiving the tool result, return a concise final text containing the exact marker from the file."

def sha(value: Any) -> str:
    return "sha256:"+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def extract_assistant_output_text(output_items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str | None:
    """只提取 Responses message/output_text 的规范文本；畸形内容返回 None。"""
    texts=[]
    for item in output_items:
        if not isinstance(item, dict):
            return None
        if item.get("type") != "message":
            continue
        content=item.get("content")
        if not isinstance(content, list):
            return None
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                return None
            texts.append(part["text"])
    return "".join(texts) if texts else None


def _replay_audit(observed: ObservationalResponsesAdapter, function_call: dict[str, Any], task: str) -> dict[str, Any]:
    """验证首轮任务与最后成功轮的完整 stateless projection。"""
    successful = [record for record in observed.request_records if record.get("outcome") == "response"]
    requests = observed.requests
    if len(successful) < 2 or len(requests) < 2:
        return {"valid": False, "reason": "insufficient_successful_requests"}
    first = requests[successful[0]["request_index"] - 1]
    replay = requests[successful[-1]["request_index"] - 1]
    first_input = first.get("input")
    initial_ok = first_input == [{"type": "message", "role": "user", "content": task}]
    history = replay.get("input")
    if not isinstance(history, list):
        return {"valid": False, "reason": "replay_input_not_list", "initial_task_valid": initial_ok}
    projected_calls = [item for item in history if isinstance(item, dict) and item.get("type") == "function_call"]
    outputs = [item for item in history if isinstance(item, dict) and item.get("type") == "function_call_output"]
    reasoning = [item for item in history if isinstance(item, dict) and item.get("type") == "reasoning"]
    messages = [item for item in history if isinstance(item, dict) and item.get("type") == "message"]
    allowed_keys = {
        "reasoning": {"type", "content"}, "message": {"type", "role", "content"},
        "function_call": {"type", "call_id", "name", "arguments"},
        "function_call_output": {"type", "call_id", "output"},
    }
    no_forbidden_fields = all(item.get("type") in allowed_keys and set(item) == allowed_keys[item.get("type")] for item in history if isinstance(item, dict))
    call_id = function_call.get("call_id")
    output_call_id = outputs[0].get("call_id") if len(outputs) == 1 else None
    replay_ok = (
        initial_ok and len(projected_calls) == 1 and len(outputs) == 1 and len(reasoning) == 1
        and projected_calls[0].get("call_id") == call_id
        and output_call_id == call_id and no_forbidden_fields
        and isinstance(outputs[0].get("output"), str)
    )
    return {"valid": replay_ok, "initial_task_valid": initial_ok, "projected_call_count": len(projected_calls), "function_output_count": len(outputs), "reasoning_count": len(reasoning), "forbidden_fields": not no_forbidden_fields, "call_id_preserved": projected_calls[0].get("call_id") == call_id if projected_calls else False, "request_hashes": [record.get("request_hash") for record in successful]}


def run_canary(*, root: str|Path, adapter: Any, sleep=None) -> dict[str,Any]:
    root=Path(root); fixture=root/"agentbench/deepseek_live_canary/CANARY.txt"; mediator=SyntheticCanaryMediator(fixture)
    observed = adapter if isinstance(adapter, ObservationalResponsesAdapter) else ObservationalResponsesAdapter(adapter)
    adapter_mode = classify_adapter_mode(observed)
    options={}
    if sleep is not None: options["sleep"]=sleep
    result=EpisodeOrchestrator(adapter=observed,request_builder=DeepSeekRequestBuilder(root),mediator=mediator,retry_policy=RetryPolicy.from_file(root/"agentbench/live_protocol/retry_policy.json"),budget_config=BudgetConfig(),recorder=AppendOnlyTrajectory(),**options).run(episode_id="phase2b-ds1-synthetic-canary-001",replicate_id=0,agent_visible_context=TASK,evaluator_private_metadata={"synthetic":True,"benchmark":False})
    provider_events=[e for e in result.events if e.get("event_type")=="provider_response"]
    calls=[e for e in result.events if e.get("event_type")=="function_call"]
    final_text=extract_assistant_output_text(provider_events[-1].get("provider_output_items",[])) if provider_events else None
    function_call=calls[0].get("function_call",{}) if len(calls)==1 else {}
    allowed_call=(len(calls)==1 and function_call.get("name")=="read_file" and mediator.invocations==[{"tool":"read_file","path":"CANARY.txt"}])
    call_id_valid=bool(function_call.get("call_id"))
    replay_audit=_replay_audit(observed,function_call,TASK)
    replay_valid=bool(replay_audit.get("valid"))
    marker=bool(final_text is not None and MARKER in final_text)
    terminal_completed=result.termination_reason=="completed"
    provider_status_valid=all(status in {None, "completed"} for status in getattr(observed, "response_statuses", []))
    model_valid=all(event.get("provider_response",{}).get("model")=="deepseek-v4-pro" for event in provider_events) and bool(provider_events)
    successful_response_count=len([record for record in observed.request_records if record.get("outcome")=="response"])
    if adapter_mode=="FAKE_ADAPTER_OFFLINE":
        accounting_valid=result.fake_provider_calls>=1 and result.live_api_calls==0 and result.network_calls==0
    elif adapter_mode=="SIMULATED_LIVE_ADAPTER_OFFLINE":
        accounting_valid=result.fake_provider_calls==0 and result.live_api_calls>=1 and result.network_calls==result.live_api_calls
    else:
        accounting_valid=result.fake_provider_calls==0 and result.live_api_calls>=1 and result.network_calls>=1
    status="PASS" if terminal_completed and provider_status_valid and successful_response_count==2 and model_valid and allowed_call and call_id_valid and replay_valid and marker and accounting_valid else "FAIL"
    return {"status":status,"adapter_mode":adapter_mode,"episode_id":result.episode_id,"termination_reason":result.termination_reason,"provider_calls":result.provider_calls,"successful_response_count":successful_response_count,"fake_provider_calls":result.fake_provider_calls,"live_api_calls":result.live_api_calls,"network_calls":result.network_calls,"actual_external_network_calls":0 if adapter_mode=="SIMULATED_LIVE_ADAPTER_OFFLINE" else result.network_calls,"mediator_invocation_count":mediator.invocation_count,"mediator_invocations":mediator.invocations,"function_call_count":len(calls),"function_calls":[e.get("function_call") for e in calls],"call_id_valid":call_id_valid,"replay_valid":replay_valid,"replay_audit":replay_audit,"model_valid":model_valid,"provider_status_valid":provider_status_valid,"terminal_completed":terminal_completed,"marker_present":marker,"final_text_hash":sha(final_text or ""),"task_hash":sha(TASK),"events":list(result.events)}
