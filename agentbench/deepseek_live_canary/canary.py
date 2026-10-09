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


def run_canary(*, root: str|Path, adapter: Any, sleep=None) -> dict[str,Any]:
    root=Path(root); fixture=root/"agentbench/deepseek_live_canary/CANARY.txt"; mediator=SyntheticCanaryMediator(fixture)
    options={}
    if sleep is not None: options["sleep"]=sleep
    result=EpisodeOrchestrator(adapter=adapter,request_builder=DeepSeekRequestBuilder(root),mediator=mediator,retry_policy=RetryPolicy.from_file(root/"agentbench/live_protocol/retry_policy.json"),budget_config=BudgetConfig(),recorder=AppendOnlyTrajectory(),**options).run(episode_id="phase2b-ds1-synthetic-canary-001",replicate_id=0,agent_visible_context=TASK,evaluator_private_metadata={"synthetic":True,"benchmark":False})
    provider_events=[e for e in result.events if e.get("event_type")=="provider_response"]
    calls=[e for e in result.events if e.get("event_type")=="function_call"]
    final_text=extract_assistant_output_text(provider_events[-1].get("provider_output_items",[])) if provider_events else None
    function_call=calls[0].get("function_call",{}) if len(calls)==1 else {}
    allowed_call=(len(calls)==1 and function_call.get("name")=="read_file" and mediator.invocations==[{"tool":"read_file","path":"CANARY.txt"}])
    call_id_valid=bool(function_call.get("call_id"))
    request_events=[e for e in result.events if e.get("event_type")=="request"]
    replay_request=next((e for e in request_events if e.get("request_kind")=="replay"), None)
    adapter_requests=list(getattr(adapter,"requests",[]))
    replay_valid=False
    if replay_request is not None and adapter_requests:
        history=adapter_requests[-1].get("input",[])
        projected=[item for item in history if isinstance(item,dict) and item.get("type")=="function_call"]
        outputs=[item for item in history if isinstance(item,dict) and item.get("type")=="function_call_output"]
        replay_valid=(len(projected)==1 and len(outputs)==1 and projected[0].get("call_id")==function_call.get("call_id") and outputs[0].get("call_id")==function_call.get("call_id"))
    marker=bool(final_text is not None and MARKER in final_text)
    terminal_completed=result.termination_reason=="completed"
    accounting_valid=result.live_api_calls==0 and result.network_calls==0 and result.fake_provider_calls>=1
    status="PASS" if terminal_completed and allowed_call and call_id_valid and replay_valid and marker and accounting_valid else "FAIL"
    return {"status":status,"episode_id":result.episode_id,"termination_reason":result.termination_reason,"provider_calls":result.provider_calls,"fake_provider_calls":result.fake_provider_calls,"live_api_calls":result.live_api_calls,"network_calls":result.network_calls,"mediator_invocation_count":mediator.invocation_count,"mediator_invocations":mediator.invocations,"function_call_count":len(calls),"function_calls":[e.get("function_call") for e in calls],"call_id_valid":call_id_valid,"replay_valid":replay_valid,"terminal_completed":terminal_completed,"marker_present":marker,"final_text_hash":sha(final_text or ""),"task_hash":sha(TASK),"events":list(result.events)}
