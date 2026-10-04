"""Provider adapter 的最小、可注入数据模型。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class FunctionCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ProviderResponse:
    id: str
    model: str
    created_at: str | int | None
    output: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    usage_details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "ProviderResponse":
        if isinstance(raw, cls):
            return raw
        def read(name: str, default: Any = None) -> Any:
            if isinstance(raw, Mapping):
                return raw.get(name, default)
            return getattr(raw, name, default)
        output_raw = read("output", ()) or ()
        output: list[dict[str, Any]] = []
        for item in output_raw:
            if isinstance(item, Mapping):
                output.append(deepcopy(dict(item)))
            elif hasattr(item, "model_dump"):
                output.append(deepcopy(item.model_dump(exclude_none=False)))
            else:
                output.append({key: getattr(item, key) for key in ("type", "id", "call_id", "name", "arguments", "content", "summary", "status") if hasattr(item, key)})
        usage_raw = read("usage", {}) or {}
        usage_details: dict[str, Any] = {}
        if isinstance(usage_raw, Mapping):
            usage = {}
            for key, value in usage_raw.items():
                if key in {"input_tokens_details", "output_tokens_details"}:
                    usage_details[key] = deepcopy(value)
                elif value is not None:
                    usage[key] = int(value)
        else:
            usage = {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                if hasattr(usage_raw, key): usage[key] = int(getattr(usage_raw, key))
            for key in ("input_tokens_details", "output_tokens_details"):
                if hasattr(usage_raw, key):
                    value = getattr(usage_raw, key)
                    usage_details[key] = value.model_dump(exclude_none=False) if hasattr(value, "model_dump") else deepcopy(value.__dict__ if hasattr(value, "__dict__") else value)
        return cls(
            id=str(read("id", "")),
            model=str(read("model", "")),
            created_at=read("created_at"),
            output=tuple(output),
            usage=usage,
            usage_details=usage_details,
        )

    def function_calls(self) -> tuple[FunctionCall, ...]:
        calls = []
        for item in self.output:
            if item.get("type") == "function_call":
                calls.append(FunctionCall(str(item.get("call_id", "")), str(item.get("name", "")), str(item.get("arguments", ""))))
        return tuple(calls)

    def has_text_output(self) -> bool:
        return any(item.get("type") in {"message", "output_text", "text"} for item in self.output)


class ResponsesAdapter(Protocol):
    def create_response(self, request: dict[str, Any]) -> ProviderResponse: ...
