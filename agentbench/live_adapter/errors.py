"""Responses adapter 错误类型。"""

from __future__ import annotations


class NetworkDisabledError(RuntimeError):
    """未注入传输层时，离线阶段禁止任何真实网络调用。"""


class ProviderError(RuntimeError):
    """可审计的 provider 错误。"""

    def __init__(self, message: str, *, error_type: str = "ProviderError", retryable: bool = False, original_exception_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable
        self.original_exception_type = original_exception_type
