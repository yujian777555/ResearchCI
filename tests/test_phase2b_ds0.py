from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.deepseek_adapter import DeepSeekRequestBuilder, FakeDeepSeekResponsesAdapter
from agentbench.deepseek_adapter.deepseek_responses import DeepSeekResponsesAdapter
from agentbench.live_adapter.errors import NetworkDisabledError
from agentbench.live_adapter.types import ProviderResponse
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy

ROOT=Path(__file__).resolve().parents[1]
MARKER='RESEARCHCI_CANARY_OK_2B2B'

def response(response_id, output):
    return ProviderResponse(response_id,'deepseek-v4-pro','2026-10-04T00:00:00Z',tuple(output),{'input_tokens':2,'output_tokens':3,'total_tokens':5})

def fc(call_id,name,args): return {'type':'function_call','call_id':call_id,'name':name,'arguments':json.dumps(args,sort_keys=True)}
def reasoning(text='think'): return {'type':'reasoning','id':'rs_1','summary':[{'type':'summary_text','text':text}]}
def msg(text): return {'type':'message','content':[{'type':'output_text','text':text}]}
def make(adapter, mediator=lambda name,args:{'admitted':True}, **kwargs):
    return EpisodeOrchestrator(adapter=adapter,request_builder=DeepSeekRequestBuilder(ROOT),mediator=mediator,retry_policy=RetryPolicy.from_file(ROOT/'agentbench/live_protocol/retry_policy.json'),sleep=lambda _:None,**kwargs)

def test_text_only_completion_and_accounting():
    adapter=FakeDeepSeekResponsesAdapter([response('r1',[msg('done')])])
    result=make(adapter).run(episode_id='ds-text',replicate_id=0,agent_visible_context='task')
    assert result.termination_reason=='completed'; assert result.provider_calls==1; assert result.fake_provider_calls==1; assert result.live_api_calls==0; assert result.network_calls==0

def test_single_function_stateless_replay_preserves_reasoning_call_and_task():
    seen=[]
    adapter=FakeDeepSeekResponsesAdapter([response('r1',[reasoning(),fc('call_1','read_file',{'path':'CANARY.txt'})]),response('r2',[msg(MARKER)])])
    result=make(adapter,lambda name,args: seen.append((name,args)) or {'admitted':True,'content':MARKER}).run(episode_id='ds-one',replicate_id=0,agent_visible_context='user task')
    assert result.termination_reason=='completed'; assert seen==[('read_file',{'path':'CANARY.txt'})]
    history=adapter.requests[1]['input']; assert history[0]=={'type':'message','role':'user','content':'user task'}
    assert history[1]['type']=='reasoning'; assert history[2]['type']=='function_call'; assert history[2]['call_id']=='call_1'
    assert history[3]['type']=='function_call_output' and history[3]['call_id']=='call_1'

def test_multiple_function_calls_replay_order_and_no_reexecution():
    seen=[]
    adapter=FakeDeepSeekResponsesAdapter([response('r1',[reasoning(),fc('call_1','read_file',{'path':'a'}),fc('call_2','read_file',{'path':'b'})]),response('r2',[msg('done')])])
    result=make(adapter,lambda name,args: seen.append((name,args)) or {'admitted':True}).run(episode_id='ds-multi',replicate_id=0,agent_visible_context='task')
    assert result.termination_reason=='completed'; assert len(seen)==2
    history=adapter.requests[1]['input']; assert [x['call_id'] for x in history[-2:]]==['call_1','call_2']
    assert [x['type'] for x in history[1:4]]==['reasoning','function_call','function_call']

def test_deepseek_requests_have_stateless_allowlist_and_generation_parity():
    adapter=FakeDeepSeekResponsesAdapter([response('r1',[fc('c','read_file',{'path':'x'})]),response('r2',[msg('done')])])
    make(adapter).run(episode_id='ds-fields',replicate_id=0,agent_visible_context='task')
    assert len(adapter.requests)==2
    allowed={'model','instructions','input','reasoning','top_p','max_output_tokens','tools','tool_choice'}
    for request in adapter.requests:
        assert set(request)==allowed; assert 'temperature' not in request; assert 'previous_response_id' not in request; assert 'store' not in request; assert 'metadata' not in request; assert 'conversation' not in request
        assert request['top_p']==0.95 and request['reasoning']=={'effort':'max'}

def test_local_schema_validation_blocks_malformed_arguments_before_mediator():
    seen=[]; adapter=FakeDeepSeekResponsesAdapter([response('r1',[fc('c','read_file',{'unknown':'x'})])])
    result=make(adapter,lambda name,args:seen.append(args) or {'admitted':True}).run(episode_id='ds-bad',replicate_id=0,agent_visible_context='task')
    assert result.termination_reason=='invalid_function_arguments'; assert seen==[]

def test_three_profile_payloads_are_compatible_without_loading_harness():
    builder=DeepSeekRequestBuilder(ROOT)
    for profile in ('tabular_sklearn','vision_pytorch','text_classification'):
        path=next((ROOT/'agentbench/scenarios').glob(f'*_{profile}.json')); state=json.loads(path.read_text())['initial_state']
        assert builder.validate_arguments('run_experiment',state['pre_run'])==state['pre_run']
        assert builder.validate_arguments('consume_cache',state['pre_cache_consume'])==state['pre_cache_consume']
        assert builder.validate_arguments('propose_aggregate',{'aggregate':state['pre_aggregate']})=={'aggregate':state['pre_aggregate']}

def test_no_network_without_injected_transport():
    with pytest.raises(NetworkDisabledError): DeepSeekResponsesAdapter().create_response({})

def test_fake_path_socket_guard(monkeypatch):
    import socket
    monkeypatch.setattr(socket,'socket',lambda *a,**k: (_ for _ in ()).throw(AssertionError('socket attempted')))
    result=make(FakeDeepSeekResponsesAdapter([response('r1',[msg('done')])])).run(episode_id='ds-net',replicate_id=0,agent_visible_context='task')
    assert result.network_calls==0

def test_historical_openai_state_fields_are_not_in_builder_contract():
    builder=DeepSeekRequestBuilder(ROOT)
    assert builder.contract['stateless_replay'] is True
    assert 'previous_response_id' in builder.contract['unsupported_request_fields']
    request=builder.build(agent_visible_context=builder.initial_history('task'),replicate_id=0,remaining_output_token_budget=100)
    assert all(name not in request for name in ('previous_response_id','conversation','store','metadata','temperature','parallel_tool_calls'))


def test_deepseek_tool_budget_blocks_21st_before_mediator():
    seen=[]
    adapter=FakeDeepSeekResponsesAdapter([response('r1',[fc(str(i),'read_file',{'path':'x'}) for i in range(21)])])
    result=make(adapter,lambda name,args:seen.append(args) or {'admitted':True}).run(episode_id='ds-tool-budget',replicate_id=0,agent_visible_context='task')
    assert result.termination_reason=='tool_budget_exhausted'; assert len(seen)==20; assert result.live_api_calls==0


def test_deepseek_output_token_budget_remains_runner_controlled():
    adapter=FakeDeepSeekResponsesAdapter([response('r1',[fc('c1','read_file',{'path':'x'})],),response('r2',[fc('c2','read_file',{'path':'x'})]),response('r3',[fc('c3','read_file',{'path':'x'})]),response('r4',[msg('done')])])
    # Replace usage with the frozen cumulative pattern while preserving fake response identity.
    adapter._items[0]=ProviderResponse('r1','deepseek-v4-pro','t',tuple([fc('c1','read_file',{'path':'x'})]),{'input_tokens':1,'output_tokens':6000,'total_tokens':6001})
    adapter._items[1]=ProviderResponse('r2','deepseek-v4-pro','t',tuple([fc('c2','read_file',{'path':'x'})]),{'input_tokens':1,'output_tokens':6000,'total_tokens':6001})
    adapter._items[2]=ProviderResponse('r3','deepseek-v4-pro','t',tuple([fc('c3','read_file',{'path':'x'})]),{'input_tokens':1,'output_tokens':4000,'total_tokens':4001})
    result=make(adapter).run(episode_id='ds-token-budget',replicate_id=0,agent_visible_context='task')
    assert result.termination_reason=='output_token_budget_exhausted'; assert [r['max_output_tokens'] for r in adapter.requests]==[16000,10000,4000]
