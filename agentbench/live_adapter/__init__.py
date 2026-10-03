"""离线可注入的 Responses adapter 实现。"""
from .errors import NetworkDisabledError, ProviderError
from .types import FunctionCall, ProviderResponse, ResponsesAdapter
from .openai_responses import OpenAIResponsesAdapter, ResponsesRequestBuilder
from .fake_provider import FakeResponsesAdapter

__all__ = [
    "FakeResponsesAdapter",
    "FunctionCall",
    "NetworkDisabledError",
    "OpenAIResponsesAdapter",
    "ProviderError",
    "ProviderResponse",
    "ResponsesAdapter",
    "ResponsesRequestBuilder",
]
