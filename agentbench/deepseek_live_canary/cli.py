"""DS-1 R4 canonical entrypoint; live modes fail closed."""
from __future__ import annotations
import argparse
import json
import tempfile
from pathlib import Path
from agentbench.deepseek_adapter.deepseek_responses import DeepSeekResponsesAdapter
from agentbench.deepseek_adapter.fake_provider import FakeDeepSeekResponsesAdapter
from agentbench.live_adapter.types import ProviderResponse
from .canary import run_canary
from .preflight import (OfflineModelListClient, PreflightAuditLog, PreflightResult,
                        QualificationGate, TransportAudit, canary_eligibility,
                        persist_preflight_result, run_preflight)

ROOT=Path(__file__).resolve().parents[2]

def _fake_response(response_id, output):
    return ProviderResponse(response_id,"deepseek-v4-pro",1,tuple(output),{"input_tokens":1,"output_tokens":1,"total_tokens":2})

def _response_sequence():
    return [_fake_response("r1", [{"type":"reasoning","content":[{"type":"reasoning_text","text":"r"}]},{"type":"function_call","call_id":"c1","name":"read_file","arguments":"{\"path\":\"CANARY.txt\"}"}]), _fake_response("r2", [{"type":"message","role":"assistant","content":[{"type":"output_text","text":"RESEARCHCI_DEEPSEEK_CANARY_OK_DS1"}]}])]

def _simulated_live_adapter():
    responses = iter(_response_sequence())
    def transport(_request):
        return next(responses)
    return DeepSeekResponsesAdapter(transport=transport)

def _run_offline_qualification(root: Path, adapter, *, corrupt: bool = False) -> tuple[int, dict]:
    log=PreflightAuditLog(root/"preflight.jsonl")
    audit=TransportAudit(max_retries=0)
    client=OfflineModelListClient(audit, response={"data":[{"id":"deepseek-v4-pro"}]})
    result=run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
    summary=persist_preflight_result(result,root/"preflight.json",log)
    if corrupt:
        summary["provider_outcome_persisted"]=False
        (root/"preflight.json").write_text(json.dumps(summary),encoding="utf-8")
    gate=QualificationGate(audit_log=log, summary_path=root/"preflight.json")
    if not gate.admit_preflight(summary): return 1, {"preflight":summary}
    outcome=run_canary(root=ROOT,adapter=adapter,sleep=lambda _:None) if gate.admit_canary(summary) else {"status":"NOT_RUN"}
    return (0 if outcome.get("status")=="PASS" else 1), {"preflight":summary,"canary":outcome}

def offline_selftest(*, corrupt=False) -> int:
    with tempfile.TemporaryDirectory() as temporary:
        try:
            base=Path(temporary)
            code_fake,_=_run_offline_qualification(base/"fake",FakeDeepSeekResponsesAdapter(_response_sequence()),corrupt=corrupt)
            if code_fake != 0: return 1
            code_live,outcome=_run_offline_qualification(base/"simulated-live",_simulated_live_adapter())
            return 0 if code_live==0 and outcome.get("canary",{}).get("adapter_mode")=="SIMULATED_LIVE_ADAPTER_OFFLINE" else 1
        except Exception:
            return 1

def main(argv=None)->int:
    parser=argparse.ArgumentParser(); parser.add_argument("mode",choices=("offline-selftest","preflight","canary")); args=parser.parse_args(argv)
    if args.mode=="offline-selftest": return offline_selftest()
    print("DS-1 R4 live mode disabled; requires later Planner authorization")
    return 2

if __name__=="__main__": raise SystemExit(main())
