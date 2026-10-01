"""确定性 append-only semantic event log 与 hash chain。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def value_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


class EventLog:
    def __init__(self, path: str | Path | None = None, *, episode_id: str = "", condition: str = ""):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.episode_id = episode_id
        self.condition = condition
        self.events: list[dict[str, Any]] = []
        self._previous_hash = "sha256:" + "0" * 64

    def append(self, *, action_type: str, lifecycle_stage: str, input_value: Any, decision: str,
               detected_rule_ids: Iterable[str] = (), repair: dict[str, Any] | None = None,
               output_value: Any = None, workspace_tree_hash: str = "", result: dict[str, Any] | None = None,
               admitted: bool = False) -> dict[str, Any]:
        event = {
            "event_index": len(self.events),
            "episode_id": self.episode_id,
            "condition": self.condition,
            "action_type": action_type,
            "lifecycle_stage": lifecycle_stage,
            "input_hash": value_hash(input_value),
            "decision": decision,
            "detected_rule_ids": sorted(set(detected_rule_ids)),
            "repair": repair,
            "output_result_hash": value_hash(output_value),
            "workspace_tree_hash": workspace_tree_hash,
            "admitted": bool(admitted),
            "result": result or {},
            "previous_event_hash": self._previous_hash,
        }
        event["event_hash"] = "sha256:" + hashlib.sha256(self._previous_hash.encode() + canonical_bytes(event)).hexdigest()
        self._previous_hash = event["event_hash"]
        self.events.append(event)
        if self.path:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return event

    @staticmethod
    def verify_chain(events: list[dict[str, Any]]) -> bool:
        previous = "sha256:" + "0" * 64
        for expected_index, event in enumerate(events):
            if event.get("event_index") != expected_index or event.get("previous_event_hash") != previous:
                return False
            payload = dict(event)
            actual_hash = payload.pop("event_hash", None)
            calculated = "sha256:" + hashlib.sha256(previous.encode() + canonical_bytes(payload)).hexdigest()
            if actual_hash != calculated:
                return False
            previous = actual_hash
        return True

    @staticmethod
    def semantic_hash(events: list[dict[str, Any]]) -> str:
        return value_hash(events)
