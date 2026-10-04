"""DS-1 独立 synthetic mediator，不加载 benchmark 状态。"""
from __future__ import annotations
from pathlib import Path

MARKER = "RESEARCHCI_DEEPSEEK_CANARY_OK_DS1"

class SyntheticCanaryMediator:
    def __init__(self, fixture: str | Path):
        self.fixture = Path(fixture)
        self.invocations: list[dict[str, str]] = []

    def __call__(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.invocations.append({"tool": tool_name, "path": str(arguments.get("path", ""))})
        if tool_name != "read_file" or arguments != {"path": "CANARY.txt"}:
            return {"admitted": False, "decision": "REJECTED", "reason": "only exact read_file(CANARY.txt) is allowed"}
        return {"admitted": True, "path": "CANARY.txt", "content": self.fixture.read_text(encoding="utf-8")}

    @property
    def invocation_count(self) -> int:
        return len(self.invocations)
