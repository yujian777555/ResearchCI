"""Interfaces for a future live execution; no provider or network code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class EpisodeLoader(Protocol):
    def load(self, episode_id: str) -> dict[str, Any]: ...


class AgentAdapter(Protocol):
    def start(self, context: dict[str, Any]) -> None: ...

    def next_action(self, observation: dict[str, Any] | None) -> dict[str, Any]: ...


class TrajectoryRecorder(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...


class EvaluationHook(Protocol):
    def inspect(self, trajectory: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RunnerConfig:
    max_steps: int
    max_tool_calls: int
    timeout_seconds: int
    token_budget: int
