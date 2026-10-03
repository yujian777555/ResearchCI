"""append-only trajectory recorder 与 evaluator 私有元数据隔离。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppendOnlyTrajectory:
    events: list[dict[str, Any]] = field(default_factory=list)

    def append(self, event: dict[str, Any]) -> None:
        self.events.append(deepcopy(event))

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self.events)


@dataclass(frozen=True)
class TrajectoryResult:
    episode_id: str
    replicate_id: int
    termination_reason: str
    events: tuple[dict[str, Any], ...]
    provider_calls: int
    fake_provider_calls: int
    live_api_calls: int
    network_calls: int

    @property
    def calls(self) -> int:
        return self.provider_calls

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "replicate_id": self.replicate_id,
            "termination_reason": self.termination_reason,
            "events": [deepcopy(event) for event in self.events],
            "provider_calls": self.provider_calls,
            "fake_provider_calls": self.fake_provider_calls,
            "live_api_calls": self.live_api_calls,
            "network_calls": self.network_calls,
        }
