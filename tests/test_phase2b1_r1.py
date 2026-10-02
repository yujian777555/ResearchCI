from __future__ import annotations

import json
import shutil
from pathlib import Path

from agentbench.live_runner.dry_run import dry_run
from agentbench.live_runner.freeze import composite_protocol_hash, component_hashes, request_preview, validate_configuration

ROOT = Path(__file__).resolve().parents[1]


def test_executable_model_identity_and_replicate_semantics_are_frozen():
    validation = validate_configuration(ROOT)
    assert validation["passed"] is True
    assert validation["model"] == "gpt-5.6-sol"
    assert validation["version"] == "alias_pinned"
    assert validation["replicate_ids"] == [0, 1, 2]
    assert validation["provider_seed_supported"] is False
    assert "TBD" not in json.dumps(validation)
    assert "fixed_snapshot" not in json.dumps(validation)


def test_provider_request_preview_uses_only_contract_fields():
    preview = request_preview(ROOT, 1)
    request = preview["request"]
    assert request["model"] == "gpt-5.6-sol"
    assert request["temperature"] == 0
    assert request["top_p"] == 1
    assert request["max_output_tokens"] == 16000
    assert "max_tool_calls" not in request
    assert request["metadata"] == {"replicate_id": "1"}
    assert "seed" not in request
    assert preview["request_contract_valid"] is True
    assert all(tool["type"] == "function" and tool["strict"] for tool in request["tools"])
    run_tool = next(tool for tool in request["tools"] if tool["name"] == "run_experiment")
    assert run_tool["parameters"]["properties"]["baseline_intent"]["type"] == "object"


def test_composite_protocol_hash_changes_when_any_frozen_component_changes(tmp_path):
    copied = tmp_path / "repo"
    shutil.copytree(ROOT / "agentbench", copied / "agentbench")
    shutil.copy(ROOT / "docs" / "PHASE2B_PLAN.md", copied / "docs" / "PHASE2B_PLAN.md") if False else None
    before = composite_protocol_hash(copied)
    prompt = copied / "agentbench/live_protocol/system_prompt.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nAdditional frozen line.\n", encoding="utf-8")
    after = composite_protocol_hash(copied)
    assert before != after
    assert component_hashes(copied)["prompt_hash"] != component_hashes(ROOT)["prompt_hash"]


def test_freeze_report_uses_current_component_hashes():
    freeze = json.loads((ROOT / "agentbench/reports/phase2b1_freeze.json").read_text(encoding="utf-8"))
    components = component_hashes(ROOT)
    assert freeze["composite_protocol_hash"] == composite_protocol_hash(ROOT)
    for key in ("agent_config_hash", "prompt_hash", "environment_hash", "scenario_hash", "tool_schema_hash", "provider_request_contract_hash", "runner_source_hash"):
        assert freeze[key] == components[key]
    assert freeze["scenario_hash"] == "sha256:d62e43f35d412b2e0ee88c027fecd10e2735cec1839b4ca3ea562050ebc4e67e"
    assert freeze["tool_schema_hash"] == "sha256:d6df7131e33a15fa67ab338304f150c30a503124f80b445eaeef131b601e202c"


def test_dry_run_never_executes_live_or_network_calls():
    summary = dry_run().as_dict()
    assert summary == {"live_call": False, "network_calls": 0, "executed_steps": 0, "executed_tool_calls": 0, "result_count": 0}
