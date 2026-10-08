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

TASK="This is a transport qualification task. Use the available read_file tool exactly once to read CANARY.txt. Do not call any other tool. After receiving the tool result, return a concise final text containing the exact marker from the file."

def sha(value: Any) -> str:
    return "sha256:"+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def run_canary(*, root: str|Path, adapter: Any) -> dict[str,Any]:
    root=Path(root); fixture=root/"agentbench/deepseek_live_canary/CANARY.txt"; mediator=SyntheticCanaryMediator(fixture)
    result=EpisodeOrchestrator(adapter=adapter,request_builder=DeepSeekRequestBuilder(root),mediator=mediator,retry_policy=RetryPolicy.from_file(root/"agentbench/live_protocol/retry_policy.json"),budget_config=BudgetConfig(),recorder=AppendOnlyTrajectory()).run(episode_id="phase2b-ds1-synthetic-canary-001",replicate_id=0,agent_visible_context=TASK,evaluator_private_metadata={"synthetic":True,"benchmark":False})
    provider_events=[e for e in result.events if e.get("event_type")=="provider_response"]
    calls=[e for e in result.events if e.get("event_type")=="function_call"]
    final_text=""
    if provider_events:
        for item in provider_events[-1].get("provider_output_items",[]):
            if item.get("type")=="message": final_text += str(item.get("content",item.get("text","")))
    return {"episode_id":result.episode_id,"termination_reason":result.termination_reason,"provider_calls":result.provider_calls,"fake_provider_calls":result.fake_provider_calls,"live_api_calls":result.live_api_calls,"network_calls":result.network_calls,"mediator_invocation_count":mediator.invocation_count,"mediator_invocations":mediator.invocations,"function_call_count":len(calls),"function_calls":[e.get("function_call") for e in calls],"marker_present":MARKER in final_text,"final_text_hash":sha(final_text),"events":list(result.events)}
