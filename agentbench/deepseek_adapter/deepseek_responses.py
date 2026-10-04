"""DeepSeek Responses adapter 与 stateless replay request builder。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from agentbench.live_adapter.errors import NetworkDisabledError, ProviderError
from agentbench.live_adapter.tool_schemas import validate_tool_payload
from agentbench.live_adapter.types import ProviderResponse


class UnsupportedReplayItemError(ValueError):
    """Provider output item 没有冻结的 DeepSeek input projection。"""


_ERROR_TYPES = {
    400: ("InvalidRequestError", False),
    401: ("AuthenticationError", False),
    402: ("InsufficientBalanceError", False),
    422: ("InvalidRequestError", False),
    429: ("RateLimitError", True),
    500: ("TransientProviderError", True),
    503: ("TransientProviderError", True),
}


def _status_code(error: BaseException) -> int | None:
    candidates = [getattr(error, "status_code", None), getattr(error, "status", None), getattr(getattr(error, "response", None), "status_code", None)]
    for value in candidates:
        try:
            if value is not None: return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _sanitized_message(error: BaseException) -> str:
    text = str(error) or type(error).__name__
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(api[_ -]?key|authorization)\s*[:=]\s*[^ ,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    return text[:1000]


def normalize_deepseek_exception(error: BaseException) -> ProviderError:
    """把 SDK/HTTP 异常归一化为 shared RetryPolicy 使用的语义。"""
    if isinstance(error, ProviderError):
        return error
    status = _status_code(error)
    exception_name = type(error).__name__
    lowered = exception_name.lower()
    if status in _ERROR_TYPES:
        error_type, retryable = _ERROR_TYPES[status]
    elif "timeout" in lowered or lowered in {"timeouterror", "apitimeouterror"}:
        error_type, retryable = "TimeoutError", True
    elif "connection" in lowered or "connect" in lowered:
        error_type, retryable = "ConnectionError", True
    elif status is not None and 500 <= status <= 599:
        error_type, retryable = "TransientProviderError", True
    else:
        error_type, retryable = "UnknownProviderError", False
    return ProviderError(_sanitized_message(error), error_type=error_type, retryable=retryable, original_exception_type=exception_name)


def _text_parts(content: Any, *, reasoning: bool, strict: bool = False) -> list[dict[str, str]]:
    if isinstance(content, str):
        return [{"type": "reasoning_text" if reasoning else "output_text", "text": content}]
    if not isinstance(content, list):
        raise UnsupportedReplayItemError("message/reasoning content must be text or a list")
    projected: list[dict[str, str]] = []
    for part in content:
        if not isinstance(part, dict) or not isinstance(part.get("text"), str) or (strict and set(part) != {"type", "text"}):
            raise UnsupportedReplayItemError("content part lacks supported text")
        part_type = "reasoning_text" if reasoning else "output_text"
        projected.append({"type": part_type, "text": part["text"]})
    if not projected:
        raise UnsupportedReplayItemError("content must contain text")
    return projected


def project_provider_output_for_replay(output_items: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 response.output 投影为 DeepSeek 支持的 input item，保持顺序与文本字节。"""
    projected: list[dict[str, Any]] = []
    for item in output_items:
        item_type = item.get("type")
        if item_type == "reasoning":
            projected.append({"type": "reasoning", "content": _text_parts(item.get("content"), reasoning=True)})
        elif item_type == "message":
            projected.append({"type": "message", "role": item.get("role", "assistant"), "content": _text_parts(item.get("content"), reasoning=False)})
        elif item_type == "function_call":
            required = ("call_id", "name", "arguments")
            if any(not isinstance(item.get(key), str) or not item[key] for key in required):
                raise UnsupportedReplayItemError("function_call requires exact call_id/name/arguments strings")
            projected.append({"type": "function_call", "call_id": item["call_id"], "name": item["name"], "arguments": item["arguments"]})
        else:
            raise UnsupportedReplayItemError(f"unsupported DeepSeek replay output type: {item_type!r}")
    return projected


def validate_deepseek_replay_input(history: list[dict[str, Any]]) -> None:
    """校验 projection 后的 input history，不允许 response-only 字段漏入。"""
    allowed_types = {"message", "reasoning", "function_call", "function_call_output"}
    for item in history:
        if not isinstance(item, dict) or item.get("type") not in allowed_types:
            raise UnsupportedReplayItemError("history contains an unsupported item")
        item_type = item["type"]
        if item_type == "message":
            if set(item) - {"type", "role", "content"} or item.get("role") not in {"assistant", "user", "system", "developer"}:
                raise UnsupportedReplayItemError("message contains response-only fields")
            _text_parts(item.get("content"), reasoning=False, strict=True)
        elif item_type == "reasoning":
            if set(item) != {"type", "content"}:
                raise UnsupportedReplayItemError("reasoning contains response-only fields")
            _text_parts(item.get("content"), reasoning=True, strict=True)
        elif item_type == "function_call":
            if set(item) != {"type", "call_id", "name", "arguments"}:
                raise UnsupportedReplayItemError("function_call contains response-only fields")
            if any(not isinstance(item.get(key), str) or not item[key] for key in ("call_id", "name", "arguments")):
                raise UnsupportedReplayItemError("function_call fields must be non-empty strings")
        elif item_type == "function_call_output":
            if set(item) != {"type", "call_id", "output"} or not isinstance(item.get("call_id"), str):
                raise UnsupportedReplayItemError("function_call_output is malformed")


class DeepSeekRequestBuilder:
    stateless_replay = True
    endpoint = "/responses"
    model = "deepseek-v4-pro"

    def __init__(self, root: str | Path, *, system_prompt: str | None = None) -> None:
        self.root = Path(root)
        self.contract = json.loads((self.root / "agentbench/deepseek_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
        self.tool_schema = json.loads((self.root / "agentbench/tool_schema.json").read_text(encoding="utf-8"))
        self.system_prompt = system_prompt if system_prompt is not None else (self.root / "agentbench/live_protocol/system_prompt.md").read_text(encoding="utf-8")
        self._tools = self._build_tools()

    def _build_tools(self) -> list[dict[str, Any]]:
        return [{"type": "function", "name": action["type"], "description": "Execute the named controlled local research action.", "parameters": deepcopy(action["parameters"])} for action in self.tool_schema["actions"]]

    @property
    def tools(self) -> list[dict[str, Any]]:
        return deepcopy(self._tools)

    def initial_history(self, agent_visible_context: Any) -> list[dict[str, Any]]:
        return [{"type": "message", "role": "user", "content": str(agent_visible_context)}]

    def validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return validate_tool_payload(tool_name, arguments, self.tool_schema["actions"])

    def _max_output(self, remaining_output_token_budget: int) -> int:
        if remaining_output_token_budget <= 0:
            raise ValueError("remaining output token budget must be positive")
        return min(128000, int(remaining_output_token_budget))

    def validate_request(self, request: dict[str, Any]) -> None:
        if set(request) != set(self.contract["request_allowlist"]):
            raise ValueError("DeepSeek request fields do not match frozen allowlist")
        if any(field in request for field in self.contract["unsupported_request_fields"]):
            raise ValueError("unsupported stateful/OpenAI field present in DeepSeek request")
        if any(field in request for field in ("temperature", "previous_response_id", "conversation", "store", "metadata", "parallel_tool_calls")):
            raise ValueError("forbidden DeepSeek request field present")
        validate_deepseek_replay_input(request["input"])

    def _request(self, history: list[dict[str, Any]], replicate_id: int, remaining_output_token_budget: int, instructions: str | None) -> dict[str, Any]:
        request = {
            "model": self.contract["model"],
            "instructions": self.system_prompt if instructions is None else instructions,
            "input": deepcopy(history),
            "reasoning": deepcopy(self.contract["reasoning"]),
            "top_p": self.contract["sampling"]["top_p"],
            "max_output_tokens": self._max_output(remaining_output_token_budget),
            "tools": self.tools,
            "tool_choice": self.contract["tool_choice"],
        }
        self.validate_request(request)
        return request

    def build(self, *, agent_visible_context: Any, replicate_id: int, remaining_output_token_budget: int, instructions: str | None = None) -> dict[str, Any]:
        return self._request(agent_visible_context, replicate_id, remaining_output_token_budget, instructions)

    def build_replay(self, *, history: list[dict[str, Any]], replicate_id: int, remaining_output_token_budget: int, instructions: str | None = None) -> dict[str, Any]:
        return self._request(history, replicate_id, remaining_output_token_budget, instructions)

    @staticmethod
    def extend_history(history: list[dict[str, Any]], provider_output_items: tuple[dict[str, Any], ...], function_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        projected = project_provider_output_for_replay(provider_output_items)
        result = deepcopy(history) + projected + [deepcopy(item) for item in function_outputs]
        validate_deepseek_replay_input(result)
        return result


class DeepSeekResponsesAdapter:
    """DeepSeek transport-injection adapter; DS-0 never reads credentials or calls a default transport."""

    adapter_kind = "deepseek_live"
    is_live_provider = True
    endpoint = "/responses"
    model = "deepseek-v4-pro"

    def __init__(self, *, transport: Callable[[dict[str, Any]], Any] | None = None, client: Any | None = None) -> None:
        self._transport = transport
        self._client = client
        self.provider_calls = 0
        self.fake_provider_calls = 0
        self.live_api_calls = 0
        self.network_calls = 0

    @property
    def calls(self) -> int:
        return self.provider_calls

    @staticmethod
    def parse_response(raw: Any) -> ProviderResponse:
        return ProviderResponse.from_raw(raw)

    def create_response(self, request: dict[str, Any]) -> ProviderResponse:
        if self._transport is None and self._client is None:
            raise NetworkDisabledError("DS-0 has no DeepSeek provider transport")
        self.provider_calls += 1
        self.live_api_calls += 1
        self.network_calls += 1
        try:
            if self._transport is not None:
                return self.parse_response(self._transport(request))
            return self.parse_response(self._client.responses.create(**request))
        except BaseException as error:
            raise normalize_deepseek_exception(error) from error
