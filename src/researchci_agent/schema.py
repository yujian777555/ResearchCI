"""Agent/harness boundary data objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentAction:
    """Agent 能请求的受控动作；payload 不包含 evaluator hidden metadata。"""

    action_type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"action_type": self.action_type, "payload": self.payload}


@dataclass(frozen=True)
class AgentObservation:
    decision: str
    action_type: str
    message: str = ""
    detected_rule_ids: tuple[str, ...] = ()
    repair: dict[str, Any] | None = None
    result: dict[str, Any] = field(default_factory=dict)


class ResearchAgent(Protocol):
    def start_episode(self, context: dict[str, Any]) -> None: ...

    def next_action(self, observation: AgentObservation | None) -> AgentAction: ...
