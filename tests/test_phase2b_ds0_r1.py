from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.deepseek_adapter import (DeepSeekRequestBuilder, FakeDeepSeekResponsesAdapter,
                                          UnsupportedReplayItemError, normalize_deepseek_exception,
                                          project_provider_output_for_replay, validate_deepseek_replay_input)
from agentbench.deepseek_adapter.deepseek_responses import DeepSeekResponsesAdapter
from agentbench.live_adapter.errors import ProviderError
from agentbench.live_adapter.types import ProviderResponse
from agentbench.live_runner.orchestrator import EpisodeOrchestrator
from agentbench.live_runner.retry import RetryPolicy

ROOT=Path(__file__).resolve().parents[1]

def raw(i, output): return ProviderResponse(f'r{i}','deepseek-v4-pro',1,tuple(output),{'input_tokens':1,'output_tokens':1,'total_tokens':2})
def call(cid='call_XYZ-123',name='propose_aggregate',arguments=' { "x" : 1 } '): return {'type':'function_call','id':'fc_response','status':'completed','call_id':cid,'name':name,'arguments':arguments}
def run(adapter, mediator=None, **kw): return EpisodeOrchestrator(adapter=adapter,request_builder=DeepSeekRequestBuilder(ROOT),mediator=mediator or (lambda n,a:{'admitted':True}),retry_policy=RetryPolicy.from_file(ROOT/'agentbench/live_protocol/retry_policy.json'),sleep=kw.pop('sleep',lambda _:None),**kw).run(episode_id='ds-r1',replicate_id=0,agent_visible_context='task')

def test_realistic_projection_strips_response_only_reasoning_fields():
    projected=project_provider_output_for_replay([{'type':'reasoning','id':'rs_abc','status':'completed','summary':[{'type':'summary_text','text':'summary'}],'encrypted_content':'secret','content':[{'type':'reasoning_text','text':'exact reasoning text'}]}])
    assert projected==[{'type':'reasoning','content':[{'type':'reasoning_text','text':'exact reasoning text'}]}]
    validate_deepseek_replay_input(projected)

def test_message_projection_preserves_text_and_strips_metadata():
    out={'type':'message','id':'msg_1','status':'completed','role':'assistant','content':[{'type':'output_text','text':'exact assistant','annotations':[{'type':'url'}]}]}
    projected=project_provider_output_for_replay([out])
    assert projected==[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'exact assistant'}]}]

def test_function_call_projection_keeps_exact_argument_string_and_id():
    original=call(); projected=project_provider_output_for_replay([original])[0]
    assert projected=={'type':'function_call','call_id':'call_XYZ-123','name':'propose_aggregate','arguments':' { "x" : 1 } '}

def test_projection_order_and_unknown_output_rejection():
    items=[{"type":"reasoning","content":[{"type":"reasoning_text","text":"r1"}]}, call("c1","read_file",'{"path":"a"}'), {"type":"reasoning","content":[{"type":"reasoning_text","text":"r2"}]}, call("c2","read_file",'{"path":"b"}'), {"type":"message","role":"assistant","content":"done"}]
    assert [x['type'] for x in project_provider_output_for_replay(items)]==['reasoning','function_call','reasoning','function_call','message']
    with pytest.raises(UnsupportedReplayItemError): project_provider_output_for_replay([{'type':'web_search_call','id':'w'}])

def test_projection_then_function_outputs_has_frozen_order():
    b=DeepSeekRequestBuilder(ROOT); history=b.extend_history(b.initial_history('task'),tuple([call('c1','read_file','{"path":"a"}'),call('c2','read_file','{"path":"b"}')]),[{'type':'function_call_output','call_id':'c1','output':'a'},{'type':'function_call_output','call_id':'c2','output':'b'}])
    assert [x['type'] for x in history]==['message','function_call','function_call','function_call_output','function_call_output']
    assert [x['call_id'] for x in history[-4:]]==['c1','c2','c1','c2']

def test_normalizer_status_and_sdk_error_mappings():
    class StatusError(Exception):
        def __init__(self,status): self.status_code=status; super().__init__(f'HTTP {status}')
    expected={400:('InvalidRequestError',False),401:('AuthenticationError',False),402:('InsufficientBalanceError',False),422:('InvalidRequestError',False),429:('RateLimitError',True),500:('TransientProviderError',True),503:('TransientProviderError',True)}
    for status,(kind,retryable) in expected.items():
        normalized=normalize_deepseek_exception(StatusError(status)); assert (normalized.error_type,normalized.retryable)==(kind,retryable)
    class APIConnectionError(Exception): pass
    class APITimeoutError(Exception): pass
    assert normalize_deepseek_exception(APIConnectionError('connect')).error_type=='ConnectionError'
    assert normalize_deepseek_exception(APITimeoutError('timeout')).error_type=='TimeoutError'
    assert normalize_deepseek_exception(ValueError('unknown')).retryable is False

def test_normalizer_sanitizes_secrets_and_keeps_type():
    class StatusError(Exception):
        status_code=401
    normalized=normalize_deepseek_exception(StatusError('Bearer sk-secret Authorization: sk-secret'))
    assert 'sk-secret' not in str(normalized); assert 'Bearer [REDACTED]' in str(normalized); assert normalized.original_exception_type=='StatusError'

class NormalizingFake(FakeDeepSeekResponsesAdapter):
    def create_response(self, request):
        try: return super().create_response(request)
        except BaseException as error: raise normalize_deepseek_exception(error) from error

class SyntheticStatusError(Exception):
    def __init__(self,status): self.status_code=status; super().__init__(f'HTTP {status}')

def test_429_enters_shared_bounded_retry():
    adapter=NormalizingFake([SyntheticStatusError(429),raw(2,[{'type':'message','content':'done'}])])
    delays=[]; result=run(adapter,sleep=delays.append)
    assert result.termination_reason=='completed'; assert delays==[1.0]; assert adapter.provider_calls==2; assert result.events[0]['event_type']=='episode_start'

def test_500_503_use_two_retries_without_step_reset():
    adapter=NormalizingFake([SyntheticStatusError(500),SyntheticStatusError(503),raw(3,[{'type':'message','content':'done'}])])
    delays=[]; result=run(adapter,sleep=delays.append)
    assert result.termination_reason=='completed'; assert delays==[1.0,2.0]; assert adapter.provider_calls==3
    responses=[e for e in result.events if e['event_type']=='provider_response']; assert responses[0]['budget_state']['executed_steps']==1 if responses else True

def test_auth_balance_invalid_errors_do_not_retry():
    for status in (400,401,402,422):
        adapter=NormalizingFake([SyntheticStatusError(status),raw(2,[{'type':'message','content':'never'}])])
        result=run(adapter,sleep=lambda _:pytest.fail('nonretryable error slept'))
        assert result.termination_reason=='provider_error'; assert adapter.provider_calls==1

def test_successful_tool_is_not_reexecuted_after_503_retry():
    adapter=NormalizingFake([raw(1,[call('c1','read_file','{"path":"x"}')]),SyntheticStatusError(503),raw(3,[{'type':'message','content':'done'}])])
    seen=[]; result=run(adapter,lambda n,a:seen.append(a) or {'admitted':True},sleep=lambda _:None)
    assert result.termination_reason=='completed'; assert len(seen)==1; assert adapter.provider_calls==3

def test_timeout_during_retry_stops_next_attempt():
    class Clock:
        value=0.0
        def __call__(self): return self.value
    clock=Clock(); adapter=NormalizingFake([SyntheticStatusError(429),raw(2,[{'type':'message','content':'never'}])])
    def sleep(_): clock.value=900
    result=run(adapter,clock=clock,sleep=sleep)
    assert result.termination_reason=='timeout_exhausted'; assert adapter.provider_calls==1

@pytest.mark.parametrize('profile',["tabular_sklearn","vision_pytorch","text_classification"])
def test_replay_projection_profile_payload_smoke(profile):
    state=json.loads(next((ROOT/'agentbench/scenarios').glob(f'*_{profile}.json')).read_text())['initial_state']
    b=DeepSeekRequestBuilder(ROOT); assert b.validate_arguments('run_experiment',state['pre_run'])==state['pre_run']


def test_input_validator_rejects_response_only_content_metadata():
    builder = DeepSeekRequestBuilder(ROOT)
    bad = builder.initial_history('task') + [{"type":"message","role":"assistant","content":[{"type":"output_text","text":"x","annotations":[]}]}]
    with pytest.raises(UnsupportedReplayItemError): validate_deepseek_replay_input(bad)


def test_production_deepseek_adapter_normalizes_transport_exception():
    class StatusError(Exception):
        status_code = 429
    def transport(_request):
        raise StatusError('rate limited')
    adapter = DeepSeekResponsesAdapter(transport=transport)
    with pytest.raises(ProviderError) as caught:
        adapter.create_response({})
    assert caught.value.error_type == 'RateLimitError'
    assert caught.value.retryable is True
    assert adapter.provider_calls == 1
