"""确定性的 fake Responses provider；绝不创建网络连接。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from .errors import ProviderError
from .types import ProviderResponse


class FakeResponsesAdapter:
    def __init__(self, responses: Iterable[Any] = (), *, errors: Iterable[BaseException] = ()) -> None:
        self._items = list(responses)
        self._errors = list(errors)
        self.requests: list[dict[str, Any]] = []
        self.calls = 0

    def create_response(self, request: dict[str, Any]) -> ProviderResponse:
        self.calls += 1
        self.requests.append(deepcopy(request))
        if self._errors:
            error = self._errors.pop(0)
            raise error
        if not self._items:
            raise ProviderError("fake provider exhausted", error_type="FakeProviderExhausted", retryable=False)
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return ProviderResponse.from_raw(deepcopy(item))


def text_response(response_id: str, *, output_tokens: int = 1, model: str = "gpt-5.6-sol") -> ProviderResponse:
    return ProviderResponse(response_id, model, "2026-10-04T00:00:00Z", ({"type": "message", "text": "done"},), {"input_tokens": 1, "output_tokens": output_tokens, "total_tokens": output_tokens + 1})


def function_response(response_id: str, calls: list[dict[str, Any]], *, output_tokens: int = 1, model: str = "gpt-5.6-sol") -> ProviderResponse:
    output = tuple({"type": "function_call", **call} for call in calls)
    return ProviderResponse(response_id, model, "2026-10-04T00:00:00Z", output, {"input_tokens": 1, "output_tokens": output_tokens, "total_tokens": output_tokens + 1})
