"""DS-1 R2 canonical entrypoint; live modes fail closed."""
from __future__ import annotations
import argparse
import tempfile
from pathlib import Path
from agentbench.deepseek_adapter.fake_provider import FakeDeepSeekResponsesAdapter
from agentbench.live_adapter.types import ProviderResponse
from .canary import run_canary
from .preflight import (OfflineModelListClient, PreflightAuditLog, PreflightResult,
                        QualificationGate, TransportAudit, canary_eligibility,
                        persist_preflight_result, run_preflight)

ROOT=Path(__file__).resolve().parents[2]

def _fake_response(response_id, output):
    return ProviderResponse(response_id,"deepseek-v4-pro",1,tuple(output),{"input_tokens":1,"output_tokens":1,"total_tokens":2})

def offline_selftest(*, corrupt=False) -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        log=PreflightAuditLog(root/"preflight.jsonl")
        audit=TransportAudit(max_retries=0)
        client=OfflineModelListClient(audit, response={"data":[{"id":"deepseek-v4-pro"}]})
        result=run_preflight(client_factory=lambda _: client, credential_present=True, audit_log=log)
        if corrupt:
            result={"status":"PASS", "target_present":True, "http_attempts_observed":1, "http_attempt_count_verified":True, "provider_outcome_persisted":False}
        try:
            if not isinstance(result,PreflightResult): return 1
            summary=persist_preflight_result(result,root/"preflight.json",log)
            gate=QualificationGate()
            if not gate.admit_preflight(summary) or not gate.admit_canary(summary): return 1
            adapter=FakeDeepSeekResponsesAdapter([_fake_response("r1",[{"type":"reasoning","content":[{"type":"reasoning_text","text":"r"}]},{"type":"function_call","call_id":"c1","name":"read_file","arguments":"{\"path\":\"CANARY.txt\"}"}]),_fake_response("r2",[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"RESEARCHCI_DEEPSEEK_CANARY_OK_DS1"}]}])])
            outcome=run_canary(root=ROOT,adapter=adapter,sleep=lambda _:None)
            return 0 if outcome["status"]=="PASS" and not gate.admit_canary(summary) else 1
        except Exception:
            return 1

def main(argv=None)->int:
    parser=argparse.ArgumentParser(); parser.add_argument("mode",choices=("offline-selftest","preflight","canary")); args=parser.parse_args(argv)
    if args.mode=="offline-selftest": return offline_selftest()
    print("DS-1 R2 live mode disabled; requires later Planner authorization")
    return 2

if __name__=="__main__": raise SystemExit(main())
