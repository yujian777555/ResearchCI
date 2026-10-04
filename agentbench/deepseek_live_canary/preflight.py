"""唯一一次 DeepSeek GET /models preflight 的离线可注入实现。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

TARGET_MODEL="deepseek-v4-pro"

@dataclass(frozen=True)
class PreflightResult:
    status: str
    credential_present: bool
    requests: int
    target_model: str
    target_present: bool
    error_class: str | None = None
    request_utc: str | None = None
    response_utc: str | None = None
    request_id: str | None = None
    target_metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status":self.status,"credential_present":self.credential_present,"requests":self.requests,"endpoint":"https://api.deepseek.com/models","target_model":self.target_model,"target_present":self.target_present,"error_class":self.error_class,"request_utc":self.request_utc,"response_utc":self.response_utc,"request_id":self.request_id,"target_metadata":self.target_metadata}

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def classify_preflight_error(error: BaseException) -> str:
    status=getattr(error,"status_code",getattr(error,"status",None))
    try: status=int(status) if status is not None else None
    except (TypeError,ValueError): status=None
    if status==401: return "FAIL_AUTH"
    if status==402: return "FAIL_BALANCE"
    if status is not None and status>=500: return "FAIL_PROVIDER"
    if isinstance(error,(TimeoutError,ConnectionError)) or "timeout" in type(error).__name__.lower(): return "FAIL_NETWORK"
    return "FAIL_PROVIDER"

def run_preflight(*, client_factory: Callable[[str], Any], credential_present: bool, sleep=None) -> PreflightResult:
    if not credential_present: return PreflightResult("BLOCKED_CREDENTIAL_MISSING",False,0,TARGET_MODEL,False)
    request_utc=_utc()
    try:
        client=client_factory("DEEPSEEK_API_KEY")
        response=client.models.list()
        response_utc=_utc()
        if isinstance(response, dict): items=response.get("data", [])
        else: items=getattr(response,"data", [])
        found=None
        for item in items:
            model_id=item.get("id") if isinstance(item,dict) else getattr(item,"id",None)
            if model_id==TARGET_MODEL:
                found={"id":TARGET_MODEL}
                break
        if found is None: return PreflightResult("FAIL_TARGET_MODEL_ABSENT",True,1,TARGET_MODEL,False,request_utc=request_utc,response_utc=response_utc)
        request_id=getattr(response,"_request_id",None)
        return PreflightResult("PASS",True,1,TARGET_MODEL,True,request_utc=request_utc,response_utc=response_utc,request_id=request_id,target_metadata=found)
    except BaseException as error:
        return PreflightResult(classify_preflight_error(error),True,1,TARGET_MODEL,False,error_class=classify_preflight_error(error),request_utc=request_utc,response_utc=_utc())
