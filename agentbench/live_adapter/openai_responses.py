"""OpenAI Responses request/response adapter（传输层依赖注入）。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .errors import NetworkDisabledError
from .types import ProviderResponse




def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ResponsesRequestBuilder:
    """严格按冻结 contract 构造 Responses 请求。"""

    def __init__(self, root: str | Path, *, system_prompt: str | None = None) -> None:
        self.root = Path(root)
        self.contract = json.loads((self.root / "agentbench/live_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
        self.tool_schema = json.loads((self.root / "agentbench/tool_schema.json").read_text(encoding="utf-8"))
        self.system_prompt = system_prompt if system_prompt is not None else (self.root / "agentbench/live_protocol/system_prompt.md").read_text(encoding="utf-8")
        self._tools = self._build_tools()

    def _build_tools(self) -> list[dict[str, Any]]:
        tools = []
        object_fields = {"baseline_intent", "candidate_intent", "current_run", "cached_artifact", "run_result", "aggregate"}
        for action in self.tool_schema["actions"]:
            properties: dict[str, Any] = {}
            for field_name in action["fields"]:
                if field_name in object_fields:
                    properties[field_name] = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
                else:
                    properties[field_name] = {"type": "string"}
            parameters = {"type": "object", "properties": properties, "required": list(action["fields"]), "additionalProperties": False}
            description = "Execute the named controlled local research action."
            tools.append({"type": "function", "name": action["type"], "description": description, "parameters": parameters, "strict": True})
        return tools

    @property
    def tools(self) -> list[dict[str, Any]]:
        return json.loads(_canonical_json(self._tools))

    def build(self, *, agent_visible_context: Any, replicate_id: int, remaining_output_token_budget: int, instructions: str | None = None) -> dict[str, Any]:
        if remaining_output_token_budget <= 0:
            raise ValueError("remaining output token budget must be positive")
        cap = int(self.contract["provider_per_response_output_limit"])
        request = {
            "model": self.contract["model_identifier"],
            "instructions": self.system_prompt if instructions is None else instructions,
            "input": agent_visible_context,
            "temperature": self.contract["sampling_fields"]["temperature"],
            "top_p": self.contract["sampling_fields"]["top_p"],
            "max_output_tokens": min(cap, int(remaining_output_token_budget)),
            "metadata": {"replicate_id": str(replicate_id)},
            "tools": self.tools,
        }
        if set(request) != set(self.contract["request_fields"]):
            raise ValueError("request fields do not match frozen contract")
        if any(field in request for field in self.contract["unsupported_request_fields"]):
            raise ValueError("unsupported provider field present")
        return request

    def continuation_input(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(call) for call in calls]


class OpenAIResponsesAdapter:
    """真实 Responses 适配器的可注入实现；本阶段未注入传输层即严格离线。"""

    endpoint = "/v1/responses"
    model = "gpt-5.6-sol"

    def __init__(self, *, transport: Callable[[dict[str, Any]], Any] | None = None, client: Any | None = None) -> None:
        self._transport = transport
        self._client = client
        self.calls = 0

    def create_response(self, request: dict[str, Any]) -> ProviderResponse:
        self.calls += 1
        if self._transport is not None:
            return ProviderResponse.from_raw(self._transport(request))
        if self._client is not None:
            response = self._client.responses.create(**request)
            return ProviderResponse.from_raw(response)
        raise NetworkDisabledError("offline phase has no provider transport")
