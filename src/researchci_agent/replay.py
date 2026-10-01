"""从 semantic events 重建 admission state。"""

from __future__ import annotations

from typing import Any


class ReplayEngine:
    def __init__(self, events: list[dict[str, Any]]):
        self.events = events

    def reconstruct(self) -> dict[str, Any]:
        state: dict[str, Any] = {"admitted_actions": [], "evidence_admitted": False, "completed": False}
        for event in self.events:
            if event.get("decision") in {"ALLOW", "POSTHOC"}:
                state["admitted_actions"].append({"event_index": event["event_index"], "action_type": event["action_type"], "lifecycle_stage": event["lifecycle_stage"], "admitted": event.get("admitted", False)})
            if event.get("admitted"):
                state["evidence_admitted"] = True
            if event["action_type"] == "finish_episode" and event.get("decision") == "ALLOW":
                state["completed"] = True
        return state


def replay_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return ReplayEngine(events).reconstruct()
