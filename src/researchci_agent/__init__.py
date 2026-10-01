"""Phase 2A autonomous research episode harness.

该包只提供本地、可重放的 scripted harness；它不连接外部模型或网络。
"""

from .conditions import Condition
from .mediator import EpisodeHarness, EpisodeResult, ResearchAgent, run_episode
from .scenarios import ScenarioSpec, generate_scenarios, load_scenarios

__all__ = [
    "Condition",
    "EpisodeHarness",
    "EpisodeResult",
    "ResearchAgent",
    "ScenarioSpec",
    "generate_scenarios",
    "load_scenarios",
    "run_episode",
]
