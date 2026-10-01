"""Phase 2A episode metric entry point."""

from __future__ import annotations

from typing import Any


def compute_episode_metrics(result: Any) -> dict[str, Any]:
    return result.metrics()
