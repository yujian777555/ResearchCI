"""OpenAI Responses request/response adapter（传输层依赖注入）。"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .errors import NetworkDisabledError
from .tool_schemas import validate_provider_tool_schemas, validate_tool_payload
from .types import ProviderResponse


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ResponsesRequestBuilder:
    """严格按冻结 contract 构造 initial 与 previous_response_id continuation 请求。"""

    def __init__(self, root: str | Path, *, system_prompt: str | None = None) -> None:
        self.root = Path(root)
        self.contract = json.loads((self.root / "agentbench/live_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
        self.tool_schema = json.loads((self.root / "agentbench/tool_schema.json").read_text(encoding="utf-8"))
        self.system_prompt = system_prompt if system_prompt is not None else (self.root / "agentbench/live_protocol/system_prompt.md").read_text(encoding="utf-8")
        self._tools = self._build_tools()

    def _build_tools(self) -> list[dict[str, Any]]:
        tools = []
        for action in self.tool_schema["actions"]:
            parameters = deepcopy(action["parameters"])
            if parameters.get("additionalProperties") is not False:
                raise ValueError(f"tool {action['type']} must reject unknown fields")
            tools.append({
                "type": "function",
                "name": action["type"],
                "description": "Execute the named controlled local research action.",
                "parameters": parameters,
                "strict": True,
            })
        validate_provider_tool_schemas(tools)
        return tools

    @property
    def tools(self) -> list[dict[str, Any]]:
        return json.loads(_canonical_json(self._tools))

    def validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return validate_tool_payload(tool_name, arguments, self.tool_schema["actions"])

    def _max_output(self, remaining_output_token_budget: int) -> int:
        if remaining_output_token_budget <= 0:
            raise ValueError("remaining output token budget must be positive")
        return min(int(self.contract["provider_per_response_output_limit"]), int(remaining_output_token_budget))

    def build(self, *, agent_visible_context: Any, replicate_id: int, remaining_output_token_budget: int, instructions: str | None = None) -> dict[str, Any]:
        request = {
            "model": self.contract["model_identifier"],
            "instructions": self.system_prompt if instructions is None else instructions,
            "input": agent_visible_context,
            "temperature": self.contract["sampling_fields"]["temperature"],
            "top_p": self.contract["sampling_fields"]["top_p"],
            "reasoning": deepcopy(self.contract["generation_config"]["reasoning"]),
            "store": self.contract["generation_config"]["store"],
            "parallel_tool_calls": self.contract["generation_config"]["parallel_tool_calls"],
            "max_output_tokens": self._max_output(remaining_output_token_budget),
            "metadata": {"replicate_id": str(replicate_id)},
            "tools": self.tools,
        }
        if set(request) != set(self.contract["initial_request_fields"]):
            raise ValueError("initial request fields do not match frozen contract")
        if any(field in request for field in self.contract["unsupported_request_fields"]):
            raise ValueError("unsupported provider field present")
        return request

    def build_continuation(self, *, previous_response_id: str, function_outputs: list[dict[str, Any]], replicate_id: int, remaining_output_token_budget: int, instructions: str | None = None) -> dict[str, Any]:
        if not isinstance(previous_response_id, str) or not previous_response_id:
            raise ValueError("previous_response_id must be the provider response id")
        request = {
            "model": self.contract["model_identifier"],
            "previous_response_id": previous_response_id,
            "input": self.continuation_input(function_outputs),
            "instructions": self.system_prompt if instructions is None else instructions,
            "temperature": self.contract["sampling_fields"]["temperature"],
            "top_p": self.contract["sampling_fields"]["top_p"],
            "reasoning": deepcopy(self.contract["generation_config"]["reasoning"]),
            "store": self.contract["generation_config"]["store"],
            "parallel_tool_calls": self.contract["generation_config"]["parallel_tool_calls"],
            "max_output_tokens": self._max_output(remaining_output_token_budget),
            "metadata": {"replicate_id": str(replicate_id)},
            "tools": self.tools,
        }
        if set(request) != set(self.contract["continuation_request_fields"]):
            raise ValueError("continuation request fields do not match frozen contract")
        return request

    @staticmethod
    def continuation_input(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(call) for call in calls]


class OpenAIResponsesAdapter:
    """真实 Responses 适配器的可注入实现；R1 离线阶段未注入传输层。"""

    endpoint = "/v1/responses"
    model = "gpt-5.6-sol"
    adapter_kind = "openai_live"
    is_live_provider = True

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

    def create_response(self, request: dict[str, Any]) -> ProviderResponse:
        if self._transport is None and self._client is None:
            raise NetworkDisabledError("offline phase has no provider transport")
        self.provider_calls += 1
        self.live_api_calls += 1
        self.network_calls += 1
        if self._transport is not None:
            return ProviderResponse.from_raw(self._transport(request))
        response = self._client.responses.create(**request)
        return ProviderResponse.from_raw(response)
