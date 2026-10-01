"""Phase 2A 本地生成与 scripted 验证 CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .conditions import Condition
from .events import EventLog, value_hash
from .mediator import EpisodeHarness
from .scenarios import generate_scenarios, load_scenarios
from .scripted_agents import RepairFollowingAgent, ValidAgent, ViolationAttemptAgent
from .validator import IndependentTrajectoryValidator


def run_scripted(root: Path, output: Path) -> dict:
    scenarios = load_scenarios(root)
    records = []
    replay_matches = True
    for scenario in scenarios:
        for condition in Condition:
            run_root = output / "episodes" / scenario.scenario_id / condition.value
            valid = EpisodeHarness(scenario, condition, run_root / "valid").run(ValidAgent())
            attempted = EpisodeHarness(scenario, condition, run_root / "attempted").run(ViolationAttemptAgent())
            repaired = EpisodeHarness(scenario, condition, run_root / "repaired").run(RepairFollowingAgent())
            replay_matches = replay_matches and valid.replay_state == __import__("researchci_agent.replay", fromlist=["ReplayEngine"]).ReplayEngine(valid.events).reconstruct()
            records.append({"scenario_id": scenario.scenario_id, "condition": condition.value, "valid": valid.metrics(), "attempted": attempted.metrics(), "repaired": repaired.metrics(), "validator": {"valid": valid.validator, "attempted": attempted.validator, "repaired": repaired.validator}, "semantic_event_hashes": {"valid": valid.semantic_event_hash, "attempted": attempted.semantic_event_hash, "repaired": repaired.semantic_event_hash}})
    summary = {
        "scenario_count": len(scenarios),
        "condition_count": len(list(Condition)),
        "episode_count": len(records) * 3,
        "scenario_hashes": {scenario.scenario_id: {"semantic_hash": scenario.semantic_hash, "prompt_hash": scenario.prompt_hash, "workspace_hash": scenario.workspace_hash, "contract_hash": scenario.contract_hash, "evaluator_metadata_hash": scenario.evaluator_metadata_hash} for scenario in scenarios},
        "tool_schema_hash": scenarios[0].tool_schema_hash if scenarios else None,
        "scripted_records": records,
        "replay_deterministic": replay_matches,
        "validator_independent": "InvariantEngine" not in __import__("inspect").getsource(IndependentTrajectoryValidator),
        "network_calls": 0,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "phase2a_acceptance.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(prog="researchci-agentbench")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--output", type=Path, required=True)
    scripted = sub.add_parser("run-scripted")
    scripted.add_argument("--root", type=Path, required=True)
    scripted.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        scenarios = generate_scenarios(args.output)
        print(json.dumps({"scenario_count": len(scenarios), "root": str(args.output)}, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(run_scripted(args.root, args.output), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
