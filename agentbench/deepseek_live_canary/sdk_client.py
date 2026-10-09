"""DS-1 的统一 SDK 构造与传输审计；R4 只接受内存 MockTransport。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import httpx2
from openai import OpenAI

from agentbench.live_runner.budget import BudgetConfig
from .preflight import PreflightAuditLog, TransportAudit, _utc

BASE_URL = "https://api.deepseek.com"


@dataclass
class SDKTransportAudit(TransportAudit):
    """SDK 调用、wire 尝试与 HTTP 完成各自计数，永不从一项推断另一项。"""

    sdk_invocations_by_endpoint: dict[str, int] = field(default_factory=lambda: {"models": 0, "responses": 0})
    attempts_by_endpoint: dict[str, int] = field(default_factory=lambda: {"models": 0, "responses": 0})
    completions_by_endpoint: dict[str, int] = field(default_factory=lambda: {"models": 0, "responses": 0})
    errors_by_endpoint: dict[str, int] = field(default_factory=lambda: {"models": 0, "responses": 0})
    wire_requests: list[dict[str, Any]] = field(default_factory=list, repr=False)
    sdk_observations: list[dict[str, Any]] = field(default_factory=list)
    compromised: bool = False
    last_http_status: int | None = None
    transport_retries: int = 0
    actual_external_network_calls: int = 0


class AuditedSDKTransport(httpx2.BaseTransport):
    """在安装的 HTTPX2 传输边界 append/fsync，不保存请求或响应原文。"""

    def __init__(self, inner: httpx2.MockTransport, audit: SDKTransportAudit):
        self.inner, self.audit = inner, audit

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        expected = {("GET", "/models"): "models", ("POST", "/responses"): "responses"}
        endpoint = expected.get((request.method, request.url.path))
        if endpoint is None or request.url.host != "api.deepseek.com" or request.url.scheme != "https":
            raise ValueError("DS-1 SDK transport endpoint mismatch")
        audit = self.audit
        audit.attempts_by_endpoint[endpoint] += 1
        # 原文只留在内存中，供最终 wire JSON 与 replay 一致性验证。
        import json
        body = json.loads(request.content) if request.content else None
        audit.wire_requests.append({"endpoint": endpoint, "body": deepcopy(body)})
        try:
            audit.before_attempt()
            response = self.inner.handle_request(request)
            audit.completions_by_endpoint[endpoint] += 1
            audit.last_http_status = response.status_code
            audit.record_response(status=response.status_code, request_id=response.headers.get("x-request-id"))
            return response
        except BaseException as error:
            audit.errors_by_endpoint[endpoint] += 1
            try:
                audit.record_error(error)
            except BaseException:
                audit.compromised = True
                raise
            raise

    def close(self) -> None:
        self.inner.close()


class _AuditedResource:
    """调用真正 SDK resource，保留返回类型和异常，不增加重试。"""

    def __init__(self, resource: Any, method: str, endpoint: str, audit: SDKTransportAudit):
        self._resource, self._method, self._endpoint, self._audit = resource, method, endpoint, audit

    def _invoke(self, *args: Any, **kwargs: Any) -> Any:
        audit, endpoint = self._audit, self._endpoint
        audit.sdk_invocations_by_endpoint[endpoint] += 1
        index = audit.sdk_invocations_by_endpoint[endpoint]
        attempt_id = f"{audit._log.run_id}:{endpoint}:{index}"
        if endpoint == "responses":
            audit._log.append({"event": "sdk_call_start", "endpoint": endpoint, "attempt_id": attempt_id,
                               "sdk_invocations": index, "max_retries": 0, "request_utc": _utc()})
        try:
            response = getattr(self._resource, self._method)(*args, **kwargs)
        except BaseException as error:
            # 不记录异常消息、headers 或 body，只记录稳定类别。
            audit._log.append({"event": "sdk_call_error", "endpoint": endpoint, "attempt_id": attempt_id,
                               "error_class": type(error).__name__, "http_status": getattr(error, "status_code", None),
                               "response_utc": _utc()})
            raise
        observation = {"endpoint": endpoint, "status": getattr(response, "status", None),
                       "response_id": getattr(response, "id", None), "model": getattr(response, "model", None),
                       "error_free": getattr(response, "error", None) is None,
                       "sdk_response_type": type(response).__name__}
        audit.sdk_observations.append(observation)
        audit._log.append({"event": "sdk_call_outcome", "endpoint": endpoint, "attempt_id": attempt_id,
                           "status": observation["status"], "provider_outcome_observed": True,
                           "response_id": observation["response_id"], "response_utc": _utc()})
        return response

    def list(self, *args: Any, **kwargs: Any) -> Any:
        if self._method != "list":
            raise AttributeError("not a models resource")
        return self._invoke(*args, **kwargs)

    def create(self, *args: Any, **kwargs: Any) -> Any:
        if self._method != "create":
            raise AttributeError("not a responses resource")
        return self._invoke(*args, **kwargs)


class AuditedSDKClient:
    """DS-1 包装层；models/responses 均使用同一真实 SDK 客户端。"""

    def __init__(self, inner: OpenAI, audit: SDKTransportAudit):
        self._inner = inner
        self._ds1_transport_audit = audit
        self._ds1_sdk_max_retries = inner.max_retries
        self._ds1_execution_mode = "SDK_MOCK_TRANSPORT_OFFLINE"
        self.models = _AuditedResource(inner.models, "list", "models", audit)
        self.responses = _AuditedResource(inner.responses, "create", "responses", audit)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def close(self) -> None:
        self._inner.close()


def build_sdk_client(*, api_key: str | None, audit_log: PreflightAuditLog,
                     transport: Any = None, base_url: str = BASE_URL) -> tuple[AuditedSDKClient, SDKTransportAudit]:
    """无需凭据读取；未注入 MockTransport 或 URL 漂移均在请求前拒绝。"""
    if not isinstance(transport, httpx2.MockTransport):
        raise RuntimeError("R4 SDK construction requires an in-memory MockTransport")
    if base_url != BASE_URL:
        raise ValueError("frozen DeepSeek base URL cannot be changed")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("explicit credential required; environment lookup is disabled")
    audit = SDKTransportAudit(max_retries=0)
    audit.bind(audit_log)
    timeout = httpx2.Timeout(float(BudgetConfig().timeout_seconds))
    http_client = httpx2.Client(transport=AuditedSDKTransport(transport, audit), trust_env=False,
                               follow_redirects=False, timeout=timeout)
    inner = OpenAI(api_key=api_key, base_url=base_url, max_retries=0,
                   http_client=http_client, timeout=timeout)
    return AuditedSDKClient(inner, audit), audit
