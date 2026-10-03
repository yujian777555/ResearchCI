"""冻结的 bounded retry policy。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RetryPolicy:
    def __init__(self, data: dict[str, Any]) -> None:
        self.max_retries = int(data["max_retries"])
        self.retryable_error_types = frozenset(data["retryable_error_types"])
        self.non_retryable_error_types = frozenset(data["non_retryable_error_types"])
        self.backoff_policy = dict(data["backoff_policy"])

    @classmethod
    def from_file(cls, path: str | Path) -> "RetryPolicy":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def backoff_seconds(self, retry_index: int) -> float:
        """计算第 retry_index 次重试前的 bounded exponential backoff。"""
        initial = float(self.backoff_policy.get("initial_seconds", 0))
        maximum = float(self.backoff_policy.get("max_seconds", initial))
        if retry_index < 0:
            raise ValueError("retry_index must be non-negative")
        return min(maximum, initial * (2 ** retry_index))

    def allows(self, error: BaseException, retry_index: int) -> bool:
        error_type = str(getattr(error, "error_type", type(error).__name__))
        retryable = bool(getattr(error, "retryable", error_type in self.retryable_error_types))
        return retryable and error_type not in self.non_retryable_error_types and retry_index < self.max_retries
