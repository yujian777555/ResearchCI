"""DeepSeek Responses adapter 与 stateless replay request builder。"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from agentbench.live_adapter.errors import NetworkDisabledError
from agentbench.live_adapter.tool_schemas import validate_tool_payload
from agentbench.live_adapter.types import ProviderResponse


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
        return deepcopy(history) + [deepcopy(item) for item in provider_output_items] + [deepcopy(item) for item in function_outputs]


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
        if self._transport is not None:
            return self.parse_response(self._transport(request))
        return self.parse_response(self._client.responses.create(**request))
