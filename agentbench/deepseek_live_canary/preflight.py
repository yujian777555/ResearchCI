"""DS-1 模型列表预检的离线可执行审计路径。

本模块只提供可注入的协调器和等价的离线 wire fake；它不会创建真实 SDK
客户端，也不会读取凭据。任何未被传输计数器证明的结果都会 fail closed。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .redaction import redact
from .secure_io import secure_append_jsonl, secure_read_text, secure_atomic_write_json, secure_file_lock
from .native_evidence import append_line as native_append_line, read_text as native_read_text, atomic_json as native_atomic_json

TARGET_MODEL = "deepseek-v4-pro"
UNKNOWN = None
_ALLOWED_EVENT_KEYS = {
    "event", "preflight_start_utc", "request_utc", "response_utc", "status",
    "credential_present", "target_model", "target_present",
    "provider_outcome_observed", "provider_outcome_persisted", "http_status",
    "request_id", "error_class", "sdk_invocations", "http_attempts_observed",
    "http_attempt_count_verified", "responses_http_attempts_observed",
    "attempt_index", "max_retries", "wire_outcome", "retryable",
    "run_id", "attempt_id", "event_seq", "previous_event_hash", "event_hash",
    "consumed",
    "endpoint", "response_id", "primary_event_hash",
    "authorization_stage", "canary_authorized",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_request_id(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 128:
        return None
    lowered = value.lower()
    if any(term in lowered for term in ("key", "secret", "token", "credential", "authorization", "bearer")):
        return None
    if re.fullmatch(r"(?:req|resp|request)[-_][A-Za-z0-9-]{1,100}", value) or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,}", value):
        return value
    return None


@dataclass
class TransportAudit:
    """安装在 fake wire path 上的单次请求计数器。"""

    max_retries: int = 0
    http_attempts: int = 0
    responses_http_attempts: int = 0
    verified: bool = False
    audit_failed: bool = False
    _log: "PreflightAuditLog | None" = None

    def bind(self, audit_log: "PreflightAuditLog | None") -> None:
        self._log = audit_log

    def _append(self, event: dict[str, Any]) -> None:
        if self._log is None:
            self.audit_failed = True
            raise RuntimeError("primary audit log is required")
        try:
            self._log.append(event)
        except BaseException:
            self.audit_failed = True
            raise

    def before_attempt(self, *, request_utc: str | None = None) -> None:
        self.http_attempts += 1
        if self._log is not None:
            self._append({
                "event": "transport_attempt", "attempt_index": self.http_attempts,
                "request_utc": request_utc or _utc(), "max_retries": self.max_retries,
                "http_attempts_observed": self.http_attempts,
            })

    def record_response(self, *, status: int | None = None, request_id: str | None = None) -> None:
        self.responses_http_attempts += 1
        self.verified = self.max_retries == 0 and self.http_attempts == self.responses_http_attempts
        if self._log is not None:
            self._append({
                "event": "transport_response", "attempt_index": self.http_attempts,
                "response_utc": _utc(), "http_status": status, "request_id": _safe_request_id(request_id),
                "wire_outcome": "response", "max_retries": self.max_retries,
                "responses_http_attempts_observed": self.responses_http_attempts,
            })

    def record_error(self, error: BaseException) -> None:
        self.verified = self.max_retries == 0 and self.http_attempts == 1
        if self._log is not None:
            self._append({
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


class AuditedHTTPTransport:
    """HTTPX transport wrapper used by the real OpenAI-compatible SDK path."""

    def __init__(self, inner: Any, audit: TransportAudit):
        self.inner = inner
        self.audit = audit

    def handle_request(self, request: Any) -> Any:
        self.audit.before_attempt()
        try:
            response = self.inner.handle_request(request)
            request_id = None
            try:
                request_id = response.headers.get("x-request-id")
            except AttributeError:
                pass
            self.audit.record_response(status=getattr(response, "status_code", None), request_id=request_id)
            return response
        except BaseException as error:
            self.audit.record_error(error)
            raise

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            close()


def build_audited_models_client(*, api_key: str | None, audit_log: PreflightAuditLog, transport: Any | None = None, base_url: str = "https://api.deepseek.com") -> tuple[Any, TransportAudit]:
    """兼容旧入口，委托给 models/responses 共用的唯一 SDK 工厂。"""
    from .sdk_client import build_sdk_client
    return build_sdk_client(api_key=api_key, audit_log=audit_log, transport=transport, base_url=base_url)


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
    run_id: str | None = None
    attempt_id: str | None = None
    primary_event_hash: str | None = None
    primary_audit_path: str | None = None
    authorization_stage: str | None = None
    canary_authorized: bool | None = None

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

    def __init__(self, path: str | Path, *, run_id: str | None = None):
        self.path = Path(path)
        self.run_id = run_id or uuid4().hex

    @staticmethod
    def _event_hash(event: dict[str, Any]) -> str:
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with secure_file_lock(self.path):
            safe = {key: redact(value) for key, value in event.items() if key in _ALLOWED_EVENT_KEYS}
            existing = self._events_unlocked() if self.path.exists() else []
            record = dict(safe)
            record["run_id"] = self.run_id
            record["event_seq"] = len(existing) + 1
            record["previous_event_hash"] = existing[-1].get("event_hash") if existing else None
            record["event_hash"] = self._event_hash(record)
            native_append_line(self.path, json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", locked=True)
        return record

    def _events_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in native_read_text(self.path, locked=True).splitlines() if line.strip()]
        previous = None
        for index, event in enumerate(events, start=1):
            if event.get("run_id") != self.run_id or event.get("event_seq") != index or event.get("previous_event_hash") != previous:
                raise ValueError("primary audit ordering or run identity mismatch")
            claimed = event.get("event_hash")
            unsigned = {key: value for key, value in event.items() if key != "event_hash"}
            if claimed != self._event_hash(unsigned):
                raise ValueError("primary audit integrity mismatch")
            previous = claimed
        return events

    def events(self) -> list[dict[str, Any]]:
        with secure_file_lock(self.path):
            return self._events_unlocked()

    @property
    def integrity_hash(self) -> str | None:
        events = self.events()
        return events[-1].get("event_hash") if events else None


def atomic_write_json(path: str | Path, value: dict[str, Any]) -> None:
    native_atomic_json(path, value)


def serialize_preflight_summary(result: PreflightResult) -> dict[str, Any]:
    if not isinstance(result, PreflightResult):
        raise TypeError("preflight summary requires PreflightResult")
    return result.as_dict()


def canary_eligibility(result: PreflightResult | dict[str, Any]) -> bool:
    if isinstance(result, dict):
        return bool(result.get("status") == "PASS" and result.get("target_present") is True and result.get("http_attempt_count_verified") is True and result.get("http_attempts_observed") == 1 and result.get("provider_outcome_persisted") is True)
    return bool(result.status == "PASS" and result.target_present is True and result.http_attempt_count_verified is True and result.http_attempts_observed == 1 and result.provider_outcome_persisted is True)


class QualificationGate:
    """一次 preflight / 一次 canary 的不可重入、可回读状态门。"""

    def __init__(self, *, audit_log: PreflightAuditLog | None = None, summary_path: str | Path | None = None) -> None:
        self.preflight_consumed = False
        self.canary_consumed = False
        self.audit_log = audit_log
        self.summary_path = Path(summary_path) if summary_path is not None else None
        self._preflight_evidence: dict[str, Any] | None = None

    def _persisted_evidence_valid(self, evidence: Any) -> bool:
        if not isinstance(evidence, dict) or self.audit_log is None or self.summary_path is None or not self.summary_path.exists():
            return False
        try:
            events = self.audit_log.events()
            readback = json.loads(native_read_text(self.summary_path))
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
            return False
        if readback != evidence or evidence.get("run_id") != self.audit_log.run_id:
            return False
        outcomes = [event for event in events if event.get("event") == "preflight_outcome_persisted"]
        if len(outcomes) != 1 or any(event.get("event") == "canary_admission_consumed" for event in events):
            return False
        outcome = outcomes[0]
        if outcome.get("event_hash") != evidence.get("primary_event_hash"):
            return False
        for key in ("status", "target_present", "http_attempts_observed", "http_attempt_count_verified", "provider_outcome_observed"):
            if outcome.get(key) != evidence.get(key):
                return False
        return evidence.get("provider_outcome_persisted") is True

    def admit_preflight(self, evidence: PreflightResult | dict[str, Any]) -> bool:
        """只接受同一 run 的已落盘 summary + primary outcome；任何尝试均不可重试。"""
        if self.preflight_consumed:
            return False
        self.preflight_consumed = True
        candidate = evidence if isinstance(evidence, dict) else None
        if candidate is not None and self._persisted_evidence_valid(candidate):
            self._preflight_evidence = deepcopy(candidate)
            return True
        return False

    def admit_canary(self, evidence: PreflightResult | dict[str, Any]) -> bool:
        candidate = evidence if isinstance(evidence, dict) else None
        if candidate is not None and (candidate.get("authorization_stage") == "PRECHECK_ONLY" or candidate.get("canary_authorized") is False):
            return False
        if not self.preflight_consumed or self.canary_consumed or candidate is None or candidate != self._preflight_evidence or not canary_eligibility(candidate) or not self._persisted_evidence_valid(candidate):
            return False
        try:
            record = self.audit_log.append({"event": "canary_admission_consumed", "attempt_id": candidate.get("attempt_id"), "consumed": True, "primary_event_hash": candidate.get("primary_event_hash")})
            self.audit_log.events()
        except (OSError, ValueError):
            return False
        self.canary_consumed = True
        return bool(record.get("event_hash"))


def persist_preflight_result(result: PreflightResult, summary_path: str | Path, audit_log: PreflightAuditLog | None = None) -> dict[str, Any]:
    if not isinstance(result, PreflightResult):
        if audit_log is not None:
            audit_log.append({"event": "preflight_summary_rejected", "error_class": "InvalidResultSchema"})
        raise TypeError("preflight summary requires PreflightResult")
    if audit_log is None:
        raise ValueError("primary audit log is required")
    if result.run_id is None or result.run_id != audit_log.run_id:
        raise ValueError("preflight result run identity does not match primary audit")
    audit_log.events()
    outcome = audit_log.append({
        "event": "preflight_outcome_persisted", "attempt_id": result.attempt_id, "status": result.status,
        "credential_present": result.credential_present, "target_model": result.target_model,
        "target_present": result.target_present, "provider_outcome_observed": result.provider_outcome_observed,
        "provider_outcome_persisted": True, "request_utc": result.request_utc,
        "response_utc": result.response_utc, "http_status": result.http_status,
        "error_class": result.error_class, "sdk_invocations": result.sdk_invocations,
        "http_attempts_observed": result.http_attempts_observed,
        "http_attempt_count_verified": result.http_attempt_count_verified,
    })
    persisted = replace(result, provider_outcome_persisted=True, primary_event_hash=outcome["event_hash"], primary_audit_path=str(audit_log.path.resolve()))
    summary = serialize_preflight_summary(persisted)
    summary_path = Path(summary_path)
    atomic_write_json(summary_path, summary)
    readback = json.loads(native_read_text(summary_path))
    if readback != summary:
        raise ValueError("preflight summary read-back mismatch")
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
    if isinstance(error, (TimeoutError, ConnectionError)) or "timeout" in type(error).__name__.lower() or "connection" in type(error).__name__.lower():
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
    if audit_log is not None and audit_log.path.exists() and audit_log.events():
        raise RuntimeError("preflight run already has primary evidence; automatic retry is disabled")
    run_id = audit_log.run_id if audit_log is not None else uuid4().hex
    attempt_id = f"{run_id}:preflight"
    if audit_log is not None:
        audit_log.append({"event": "preflight_start", "attempt_id": attempt_id, "preflight_start_utc": started, "credential_present": credential_present, "target_model": TARGET_MODEL})
    if not credential_present:
        result = PreflightResult("BLOCKED_CREDENTIAL_MISSING", False, preflight_start_utc=started, run_id=run_id, attempt_id=attempt_id)
        if audit_log is not None:
            audit_log.append({"event": "preflight_blocked_credential_missing", "attempt_id": attempt_id, "preflight_start_utc": started})
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
            audit_log.append({"event": "sdk_invocation", "attempt_id": attempt_id, "sdk_invocations": sdk_invocations, "request_utc": request_utc, "target_model": TARGET_MODEL})
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
        result = PreflightResult(status, True, target_present=(True if found is not None else False), sdk_invocations=sdk_invocations, http_attempts_observed=attempts, http_attempt_count_verified=verified, responses_http_attempts_observed=response_attempts, provider_outcome_observed=True, preflight_start_utc=started, request_utc=request_utc, response_utc=response_utc, request_id=_safe_request_id(getattr(response, "_request_id", None)), target_metadata=found, run_id=run_id, attempt_id=attempt_id)
    except Exception as error:
        transport = getattr(client, "_ds1_transport_audit", None) if client is not None else None
        result = PreflightResult(classify_preflight_error(error), True, target_present=UNKNOWN, sdk_invocations=sdk_invocations, http_attempts_observed=getattr(transport, "http_attempts", UNKNOWN), http_attempt_count_verified=False, responses_http_attempts_observed=getattr(transport, "responses_http_attempts", UNKNOWN), provider_outcome_observed=False, preflight_start_utc=started, request_utc=request_utc, response_utc=_utc(), http_status=_error_status(error), error_class=classify_preflight_error(error), run_id=run_id, attempt_id=attempt_id)
    if transport is not None and (getattr(transport, "audit_failed", False) or getattr(transport, "compromised", False)):
        raise RuntimeError("primary audit persistence failed; preflight outcome is UNKNOWN")
    if audit_log is not None:
        audit_log.append({"event": "preflight_result_observed", "status": result.status, "credential_present": True, "target_model": TARGET_MODEL, "target_present": result.target_present, "provider_outcome_observed": result.provider_outcome_observed, "request_utc": result.request_utc, "response_utc": result.response_utc, "http_status": result.http_status, "error_class": result.error_class, "sdk_invocations": result.sdk_invocations, "http_attempts_observed": result.http_attempts_observed, "http_attempt_count_verified": result.http_attempt_count_verified})
    return result
