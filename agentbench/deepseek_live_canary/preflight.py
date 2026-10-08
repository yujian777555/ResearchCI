"""可审计、可注入的 DS-1 /models preflight（R1 离线可测试）。"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable

TARGET_MODEL="deepseek-v4-pro"

def _utc() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

@dataclass(frozen=True)
class PreflightResult:
    status: str
    credential_present: bool
    target_model: str = TARGET_MODEL
    target_present: bool | None = None
    sdk_invocations: int = 0
    http_attempts_observed: int | None = None
    http_attempt_count_verified: bool = False
    responses_http_attempts_observed: int = 0
    provider_outcome_observed: bool = False
    provider_outcome_persisted: bool = False
    preflight_start_utc: str | None = None
    request_utc: str | None = None
    response_utc: str | None = None
    request_id: str | None = None
    http_status: int | None = None
    error_class: str | None = None
    target_metadata: dict[str, Any] | None = None
    @property
    def requests(self) -> int: return self.sdk_invocations
    def as_dict(self) -> dict[str,Any]:
        data=asdict(self); data["requests"]=self.requests; data["endpoint"]="https://api.deepseek.com/models"; data["actual_http_request_count"]="UNKNOWN" if self.http_attempts_observed is None else self.http_attempts_observed; return data

class PreflightAuditLog:
    def __init__(self,path: str|Path): self.path=Path(path)
    def append(self,event: dict[str,Any]) -> None:
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a",encoding="utf-8",newline="\n") as handle:
            handle.write(json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n"); handle.flush(); os.fsync(handle.fileno())

def atomic_write_json(path: str|Path, value: dict[str,Any]) -> None:
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_suffix(path.suffix+".tmp"); temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n"); temporary.replace(path)

def serialize_preflight_summary(result: PreflightResult) -> dict[str,Any]:
    if not isinstance(result,PreflightResult): raise TypeError("preflight summary requires PreflightResult")
    return result.as_dict()

def persist_preflight_result(result: PreflightResult, summary_path: str|Path, audit_log: PreflightAuditLog|None=None) -> dict[str,Any]:
    if not isinstance(result,PreflightResult):
        if audit_log is not None: audit_log.append({"event":"preflight_summary_rejected","reason":"invalid_result_schema"})
        raise TypeError("preflight summary requires PreflightResult")
    if audit_log is not None: audit_log.append({"event":"preflight_result_observed","status":result.status,"credential_present":result.credential_present,"target_model":result.target_model,"target_present":result.target_present,"provider_outcome_observed":result.provider_outcome_observed,"request_utc":result.request_utc,"response_utc":result.response_utc,"http_status":result.http_status,"error_class":result.error_class})
    summary=serialize_preflight_summary(result); atomic_write_json(summary_path,summary); return summary

def classify_preflight_error(error: BaseException) -> str:
    status=getattr(error,"status_code",getattr(error,"status",None))
    try: status=int(status) if status is not None else None
    except (TypeError,ValueError): status=None
    if status==401: return "FAIL_AUTH"
    if status==402: return "FAIL_BALANCE"
    if status is not None and status>=500: return "FAIL_PROVIDER"
    if isinstance(error,(TimeoutError,ConnectionError)) or "timeout" in type(error).__name__.lower(): return "FAIL_NETWORK"
    return "FAIL_PROVIDER"

def run_preflight(*, client_factory: Callable[[str],Any], credential_present: bool, audit_log: PreflightAuditLog|None=None) -> PreflightResult:
    started=_utc()
    if not credential_present:
        result=PreflightResult("BLOCKED_CREDENTIAL_MISSING",False,preflight_start_utc=started)
        if audit_log: audit_log.append({"event":"preflight_blocked_credential_missing","preflight_start_utc":started})
        return result
    request_utc=_utc()
    try:
        client=client_factory("DEEPSEEK_API_KEY"); response=client.models.list(); response_utc=_utc(); items=response.get("data",[]) if isinstance(response,dict) else getattr(response,"data",[]); found=None
        for item in items:
            model_id=item.get("id") if isinstance(item,dict) else getattr(item,"id",None)
            if model_id==TARGET_MODEL: found={"id":TARGET_MODEL}; break
        result=PreflightResult("PASS" if found else "FAIL_TARGET_MODEL_ABSENT",True,target_present=bool(found),sdk_invocations=1,provider_outcome_observed=True,preflight_start_utc=started,request_utc=request_utc,response_utc=response_utc,request_id=getattr(response,"_request_id",None),target_metadata=found)
    except BaseException as error:
        result=PreflightResult(classify_preflight_error(error),True,target_present=None,sdk_invocations=1,provider_outcome_observed=False,preflight_start_utc=started,request_utc=request_utc,response_utc=_utc(),error_class=classify_preflight_error(error))
    if audit_log: audit_log.append({"event":"preflight_result_observed","status":result.status,"credential_present":True,"target_model":TARGET_MODEL,"target_present":result.target_present,"provider_outcome_observed":result.provider_outcome_observed,"request_utc":result.request_utc,"response_utc":result.response_utc,"http_status":result.http_status,"error_class":result.error_class})
    return result
