"""DS-1 模型列表预检的离线可执行审计路径。

本模块只提供可注入的协调器和等价的离线 wire fake；它不会创建真实 SDK
客户端，也不会读取凭据。任何未被传输计数器证明的结果都会 fail closed。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any, Callable

from .redaction import redact

TARGET_MODEL = "deepseek-v4-pro"
UNKNOWN = None
_ALLOWED_EVENT_KEYS = {
    "event", "preflight_start_utc", "request_utc", "response_utc", "status",
    "credential_present", "target_model", "target_present",
    "provider_outcome_observed", "provider_outcome_persisted", "http_status",
    "request_id", "error_class", "sdk_invocations", "http_attempts_observed",
    "http_attempt_count_verified", "responses_http_attempts_observed",
    "attempt_index", "max_retries", "wire_outcome", "retryable",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class TransportAudit:
    """安装在 fake wire path 上的单次请求计数器。"""

    max_retries: int = 0
    http_attempts: int = 0
    responses_http_attempts: int = 0
    verified: bool = False
    _log: "PreflightAuditLog | None" = None

    def bind(self, audit_log: "PreflightAuditLog | None") -> None:
        self._log = audit_log

    def before_attempt(self, *, request_utc: str | None = None) -> None:
        self.http_attempts += 1
        if self._log is not None:
            self._log.append({
                "event": "transport_attempt", "attempt_index": self.http_attempts,
                "request_utc": request_utc or _utc(), "max_retries": self.max_retries,
                "http_attempts_observed": self.http_attempts,
            })

    def record_response(self, *, status: int | None = None, request_id: str | None = None) -> None:
        self.responses_http_attempts += 1
        self.verified = self.max_retries == 0 and self.http_attempts == self.responses_http_attempts
        if self._log is not None:
            self._log.append({
                "event": "transport_response", "attempt_index": self.http_attempts,
                "response_utc": _utc(), "http_status": status, "request_id": request_id,
                "wire_outcome": "response", "max_retries": self.max_retries,
                "responses_http_attempts_observed": self.responses_http_attempts,
            })

    def record_error(self, error: BaseException) -> None:
        self.verified = self.max_retries == 0 and self.http_attempts == 1
        if self._log is not None:
            self._log.append({
                "event": "transport_error", "attempt_index": self.http_attempts,
                "response_utc": _utc(), "error_class": type(error).__name__,
                "wire_outcome": "error", "max_retries": self.max_retries,
            })


class OfflineModelListClient:
    """等价 fake wire path，分离 SDK invocation 与 HTTP attempt。"""

    def __init__(self, audit: TransportAudit, response: Any = None, error: BaseException | None = None) -> None:
        self._ds1_transport_audit = audit
        self.models = self._Models(self, response, error)

    class _Models:
        def __init__(self, client: "OfflineModelListClient", response: Any, error: BaseException | None) -> None:
            self._client, self._response, self._error = client, response, error

        def list(self) -> Any:
            audit = self._client._ds1_transport_audit
            audit.before_attempt()
            try:
                if self._error is not None:
                    raise self._error
                response = self._response if self._response is not None else {"data": []}
                audit.record_response(status=getattr(response, "status_code", None), request_id=getattr(response, "_request_id", None))
                return response
            except BaseException as error:
                audit.record_error(error)
                raise


@dataclass(frozen=True)
class PreflightResult:
    status: str
    credential_present: bool
    target_model: str = TARGET_MODEL
    target_present: bool | None = UNKNOWN
    sdk_invocations: int = 0
    http_attempts_observed: int | None = UNKNOWN
    http_attempt_count_verified: bool = False
    responses_http_attempts_observed: int | None = UNKNOWN
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
    def requests(self) -> int:
        return self.sdk_invocations

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requests"] = self.requests
        data["endpoint"] = "https://api.deepseek.com/models"
        data["actual_http_request_count"] = "UNKNOWN" if self.http_attempts_observed is None else self.http_attempts_observed
        return redact(data)


class PreflightAuditLog:
    """append + flush + fsync 的 primary evidence log。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event: dict[str, Any]) -> None:
        safe = {key: redact(value) for key, value in event.items() if key in _ALLOWED_EVENT_KEYS}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_write_json(path: str | Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def serialize_preflight_summary(result: PreflightResult) -> dict[str, Any]:
    if not isinstance(result, PreflightResult):
        raise TypeError("preflight summary requires PreflightResult")
    return result.as_dict()


def canary_eligibility(result: PreflightResult | dict[str, Any]) -> bool:
    if isinstance(result, dict):
        return bool(result.get("status") == "PASS" and result.get("target_present") is True and result.get("http_attempt_count_verified") is True and result.get("http_attempts_observed") == 1 and result.get("provider_outcome_persisted") is True)
    return bool(result.status == "PASS" and result.target_present is True and result.http_attempt_count_verified is True and result.http_attempts_observed == 1 and result.provider_outcome_persisted is True)


class QualificationGate:
    """一次 preflight / 一次 canary 的不可重入状态门。"""

    def __init__(self) -> None:
        self.preflight_consumed = False
        self.canary_consumed = False
        self._preflight_evidence: PreflightResult | dict[str, Any] | None = None

    def admit_preflight(self, evidence: PreflightResult | dict[str, Any]) -> bool:
        """记录一次预检终态；失败、未知或成功都不可自动重试。"""
        if self.preflight_consumed:
            return False
        self.preflight_consumed = True
        self._preflight_evidence = deepcopy(evidence)
        return isinstance(evidence, (PreflightResult, dict))

    def admit_canary(self, evidence: PreflightResult | dict[str, Any]) -> bool:
        if not self.preflight_consumed or self.canary_consumed or evidence != self._preflight_evidence or not canary_eligibility(evidence):
            return False
        self.canary_consumed = True
        return True


def persist_preflight_result(result: PreflightResult, summary_path: str | Path, audit_log: PreflightAuditLog | None = None) -> dict[str, Any]:
    if not isinstance(result, PreflightResult):
        if audit_log is not None:
            audit_log.append({"event": "preflight_summary_rejected", "error_class": "InvalidResultSchema"})
        raise TypeError("preflight summary requires PreflightResult")
    if audit_log is None:
        raise ValueError("primary audit log is required")
    audit_log.append({
        "event": "preflight_outcome_persisted", "status": result.status,
        "credential_present": result.credential_present, "target_model": result.target_model,
        "target_present": result.target_present, "provider_outcome_observed": result.provider_outcome_observed,
        "provider_outcome_persisted": True, "request_utc": result.request_utc,
        "response_utc": result.response_utc, "http_status": result.http_status,
        "error_class": result.error_class, "sdk_invocations": result.sdk_invocations,
        "http_attempts_observed": result.http_attempts_observed,
        "http_attempt_count_verified": result.http_attempt_count_verified,
    })
    persisted = replace(result, provider_outcome_persisted=True)
    summary = serialize_preflight_summary(persisted)
    atomic_write_json(summary_path, summary)
    return summary


def classify_preflight_error(error: BaseException) -> str:
    status = getattr(error, "status_code", getattr(error, "status", None))
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status == 401:
        return "FAIL_AUTH"
    if status == 402:
        return "FAIL_BALANCE"
    if status is not None and status >= 500:
        return "FAIL_PROVIDER"
    if isinstance(error, (TimeoutError, ConnectionError)) or "timeout" in type(error).__name__.lower():
        return "FAIL_NETWORK"
    return "FAIL_PROVIDER"


def _error_status(error: BaseException) -> int | None:
    value = getattr(error, "status_code", getattr(error, "status", None))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def run_preflight(*, client_factory: Callable[[str], Any], credential_present: bool, audit_log: PreflightAuditLog | None = None) -> PreflightResult:
    """执行一次受控模型列表调用；没有 wire audit 就明确拒绝 PASS。"""
    started = _utc()
    if audit_log is not None:
        audit_log.append({"event": "preflight_start", "preflight_start_utc": started, "credential_present": credential_present, "target_model": TARGET_MODEL})
    if not credential_present:
        result = PreflightResult("BLOCKED_CREDENTIAL_MISSING", False, preflight_start_utc=started)
        if audit_log is not None:
            audit_log.append({"event": "preflight_blocked_credential_missing", "preflight_start_utc": started})
        return result

    request_utc = _utc()
    client: Any | None = None
    sdk_invocations = 0
    try:
        client = client_factory("DEEPSEEK_API_KEY")
        sdk_invocations = 1
        transport = getattr(client, "_ds1_transport_audit", None)
        if transport is not None and hasattr(transport, "bind"):
            transport.bind(audit_log)
        if audit_log is not None:
            audit_log.append({"event": "sdk_invocation", "sdk_invocations": sdk_invocations, "request_utc": request_utc, "target_model": TARGET_MODEL})
        response = client.models.list()
        response_utc = _utc()
        items = response.get("data", []) if isinstance(response, dict) else getattr(response, "data", [])
        found = None
        for item in items or []:
            model_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            if model_id == TARGET_MODEL:
                found = {"id": TARGET_MODEL}
                break
        attempts = getattr(transport, "http_attempts", UNKNOWN) if transport is not None else UNKNOWN
        response_attempts = getattr(transport, "responses_http_attempts", UNKNOWN) if transport is not None else UNKNOWN
        audit_events = audit_log.events() if audit_log is not None else []
        transport_evidence = any(event.get("event") == "transport_attempt" for event in audit_events) and any(event.get("event") == "transport_response" for event in audit_events)
        verified = bool(getattr(transport, "verified", False) and transport_evidence) if transport is not None else False
        status = "PASS" if found is not None and verified and attempts == 1 and response_attempts == 1 else ("FAIL_TRANSPORT_UNVERIFIED" if found is not None else "FAIL_TARGET_MODEL_ABSENT")
        result = PreflightResult(status, True, target_present=(True if found is not None else False), sdk_invocations=sdk_invocations, http_attempts_observed=attempts, http_attempt_count_verified=verified, responses_http_attempts_observed=response_attempts, provider_outcome_observed=True, preflight_start_utc=started, request_utc=request_utc, response_utc=response_utc, request_id=getattr(response, "_request_id", None), target_metadata=found)
    except BaseException as error:
        transport = getattr(client, "_ds1_transport_audit", None) if client is not None else None
        result = PreflightResult(classify_preflight_error(error), True, target_present=UNKNOWN, sdk_invocations=sdk_invocations, http_attempts_observed=getattr(transport, "http_attempts", UNKNOWN), http_attempt_count_verified=False, responses_http_attempts_observed=getattr(transport, "responses_http_attempts", UNKNOWN), provider_outcome_observed=False, preflight_start_utc=started, request_utc=request_utc, response_utc=_utc(), http_status=_error_status(error), error_class=classify_preflight_error(error))
    if audit_log is not None:
        audit_log.append({"event": "preflight_result_observed", "status": result.status, "credential_present": True, "target_model": TARGET_MODEL, "target_present": result.target_present, "provider_outcome_observed": result.provider_outcome_observed, "request_utc": result.request_utc, "response_utc": result.response_utc, "http_status": result.http_status, "error_class": result.error_class, "sdk_invocations": result.sdk_invocations, "http_attempts_observed": result.http_attempts_observed, "http_attempt_count_verified": result.http_attempt_count_verified})
    return result
