"""非执行 dry-run：只检查接口形状，不加载模型、不访问网络、不运行情景。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DryRunSummary:
    live_call: bool
    network_calls: int
    executed_steps: int
    executed_tool_calls: int
    result_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "live_call": self.live_call,
            "network_calls": self.network_calls,
            "executed_steps": self.executed_steps,
            "executed_tool_calls": self.executed_tool_calls,
            "result_count": self.result_count,
        }


def dry_run() -> DryRunSummary:
    """返回零执行摘要；该入口不能触发模型、工具或 benchmark。"""
    return DryRunSummary(False, 0, 0, 0, 0)
