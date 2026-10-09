"""DS-1 专用的内存请求观测器。

观测器包裹已冻结的 provider adapter，不修改请求、响应、计数器、异常或
重试行为。请求原文只保存在当前进程内供资格判断使用，持久化结果只包含
结构摘要和哈希。
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _item_structure(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"type": type(item).__name__}
    result: dict[str, Any] = {"type": item.get("type"), "keys": sorted(item.keys())}
    if item.get("type") in {"function_call", "function_call_output"}:
        result["call_id"] = item.get("call_id")
        if item.get("type") == "function_call":
            result["name"] = item.get("name")
    if item.get("type") == "message":
        result["role"] = item.get("role")
        content = item.get("content")
        result["content_types"] = [part.get("type") for part in content] if isinstance(content, list) and all(isinstance(part, dict) for part in content) else type(content).__name__
    return result


class ObservationalResponsesAdapter:
    """在 create_response 边界记录结构摘要，同时透明代理 adapter。"""

    def __init__(self, inner: Any):
        self.inner = inner
        self.adapter_kind = getattr(inner, "adapter_kind", type(inner).__name__)
        self.is_live_provider = bool(getattr(inner, "is_live_provider", False))
        self._request_snapshots: list[dict[str, Any]] = []
        self.request_records: list[dict[str, Any]] = []
        self.response_statuses: list[str | None] = []

    @property
    def requests(self) -> list[dict[str, Any]]:
        # 只为当前进程的 replay audit 暴露 immutable-ish deep copies；不落盘。
        return [deepcopy(record["request"]) for record in self._request_snapshots]

    def create_response(self, request: dict[str, Any]) -> Any:
        snapshot = deepcopy(request)
        record = {
            "request": snapshot,
            "request_hash": _hash(snapshot),
            "request_index": len(self._request_snapshots) + 1,
        }
        self._request_snapshots.append(record)
        summary = {
            "request_index": record["request_index"],
            "request_hash": record["request_hash"],
            "model": request.get("model"),
            "input_hash": _hash(request.get("input")),
            "input_structure": [_item_structure(item) for item in request.get("input", [])] if isinstance(request.get("input"), list) else {"type": type(request.get("input")).__name__},
        }
        try:
            response = self.inner.create_response(request)
        except BaseException as error:
            summary.update({"outcome": "error", "error_class": type(error).__name__})
            self.request_records.append(summary)
            raise
        inner_client = getattr(self.inner, "_client", None)
        transport_audit = getattr(inner_client, "_ds1_transport_audit", None)
        provider_status = None
        if transport_audit is not None and getattr(transport_audit, "sdk_observations", None):
            provider_status = transport_audit.sdk_observations[-1].get("status")
        self.response_statuses.append(provider_status)
        summary.update({
            "outcome": "response",
            "provider_status": provider_status,
            "response_id": getattr(response, "id", None),
            "response_hash": _hash(response.output if hasattr(response, "output") else response),
        })
        self.request_records.append(summary)
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def classify_adapter_mode(adapter: Any) -> str:
    """区分 fake、注入离线 transport 的 simulated-live 和真正 live。"""
    inner = getattr(adapter, "inner", adapter)
    if getattr(inner, "is_live_provider", False):
        client = getattr(inner, "_client", None)
        if getattr(client, "_ds1_execution_mode", None) == "SDK_MOCK_TRANSPORT_OFFLINE":
            return "SIMULATED_LIVE_ADAPTER_OFFLINE"
        if getattr(inner, "_transport", None) is not None:
            return "SIMULATED_LIVE_ADAPTER_OFFLINE"
        return "LIVE_ADAPTER"
    return "FAKE_ADAPTER_OFFLINE"

