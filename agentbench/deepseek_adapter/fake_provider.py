"""确定性的 DeepSeek stateless fake provider。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from agentbench.live_adapter.errors import ProviderError
from agentbench.live_adapter.types import ProviderResponse


class FakeDeepSeekResponsesAdapter:
    adapter_kind = "deepseek_fake"
    is_live_provider = False

    def __init__(self, responses: Iterable[Any] = ()) -> None:
        self._items = list(responses)
        self._last_response: ProviderResponse | None = None
        self._last_output_items: list[dict[str, Any]] = []
        self._expected_call_ids: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.provider_calls = 0
        self.fake_provider_calls = 0
        self.live_api_calls = 0
        self.network_calls = 0

    @property
    def calls(self) -> int:
        return self.provider_calls

    def _validate_request(self, request: dict[str, Any]) -> None:
        allowed = {"model", "instructions", "input", "reasoning", "top_p", "max_output_tokens", "tools", "tool_choice"}
        if set(request) != allowed:
            raise AssertionError(f"DeepSeek request allowlist mismatch: {sorted(set(request) ^ allowed)}")
        if request["model"] != "deepseek-v4-pro" or request["top_p"] != 0.95 or request["reasoning"] != {"effort": "max"}:
            raise AssertionError("DeepSeek generation configuration drift")
        if "temperature" in request or "previous_response_id" in request or "conversation" in request or "store" in request or "metadata" in request or "parallel_tool_calls" in request:
            raise AssertionError("forbidden stateful/OpenAI field in DeepSeek request")
        if self._last_response is not None:
            history = request["input"]
            if self._last_output_items:
                output_start = len(history) - len(self._expected_call_ids) - len(self._last_output_items)
                if history[output_start:output_start + len(self._last_output_items)] != self._last_output_items:
                    raise AssertionError("provider output history was not preserved")
                observed_outputs = history[output_start + len(self._last_output_items):]
                observed_ids = [item.get("call_id") for item in observed_outputs]
                if observed_ids != self._expected_call_ids:
                    raise AssertionError("function output call IDs were not preserved")

    def create_response(self, request: dict[str, Any]) -> ProviderResponse:
        self._validate_request(request)
        self.provider_calls += 1
        self.fake_provider_calls += 1
        self.requests.append(deepcopy(request))
        if not self._items:
            raise ProviderError("DeepSeek fake provider exhausted", error_type="FakeProviderExhausted", retryable=False)
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        response = ProviderResponse.from_raw(deepcopy(item))
        self._last_response = response
        self._last_output_items = [deepcopy(output) for output in response.output]
        self._expected_call_ids = [str(output.get("call_id")) for output in response.output if output.get("type") == "function_call"]
        return response
