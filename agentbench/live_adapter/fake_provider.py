"""确定性的 fake Responses provider；绝不创建网络连接。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from .errors import ProviderError
from .types import ProviderResponse


class FakeResponsesAdapter:
    adapter_kind = "fake"
    is_live_provider = False

    def __init__(self, responses: Iterable[Any] = (), *, errors: Iterable[BaseException] = (), enforce_continuation: bool = True) -> None:
        self._items = list(responses)
        self._errors = list(errors)
        self._last_response: ProviderResponse | None = None
        self._enforce_continuation = enforce_continuation
        self.requests: list[dict[str, Any]] = []
        self.provider_calls = 0
        self.fake_provider_calls = 0
        self.live_api_calls = 0
        self.network_calls = 0

    @property
    def calls(self) -> int:
        return self.provider_calls

    def _check_continuation(self, request: dict[str, Any]) -> None:
        if not self._enforce_continuation:
            return
        previous_id = request.get("previous_response_id")
        if self._last_response is None:
            if previous_id is not None:
                raise AssertionError("initial fake request must not contain previous_response_id")
            return
        expected_calls = self._last_response.function_calls()
        if expected_calls:
            if previous_id != self._last_response.id:
                raise AssertionError("continuation previous_response_id does not match prior response.id")
            outputs = request.get("input")
            expected_ids = [call.call_id for call in expected_calls]
            observed_ids = [item.get("call_id") for item in outputs or [] if isinstance(item, dict) and item.get("type") == "function_call_output"]
            if observed_ids != expected_ids:
                raise AssertionError("continuation function_call_output call_ids do not match provider call_ids")
        elif previous_id is not None:
            raise AssertionError("request after a completed response must not continue")

    def create_response(self, request: dict[str, Any]) -> ProviderResponse:
        self._check_continuation(request)
        self.provider_calls += 1
        self.fake_provider_calls += 1
        self.requests.append(deepcopy(request))
        if self._errors:
            raise self._errors.pop(0)
        if not self._items:
            raise ProviderError("fake provider exhausted", error_type="FakeProviderExhausted", retryable=False)
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        response = ProviderResponse.from_raw(deepcopy(item))
        self._last_response = response
        return response


def text_response(response_id: str, *, output_tokens: int = 1, model: str = "gpt-5.6-sol") -> ProviderResponse:
    return ProviderResponse(response_id, model, "2026-10-04T00:00:00Z", ({"type": "message", "text": "done"},), {"input_tokens": 1, "output_tokens": output_tokens, "total_tokens": output_tokens + 1})


def function_response(response_id: str, calls: list[dict[str, Any]], *, output_tokens: int = 1, model: str = "gpt-5.6-sol") -> ProviderResponse:
    output = tuple({"type": "function_call", **call} for call in calls)
    return ProviderResponse(response_id, model, "2026-10-04T00:00:00Z", output, {"input_tokens": 1, "output_tokens": output_tokens, "total_tokens": output_tokens + 1})
