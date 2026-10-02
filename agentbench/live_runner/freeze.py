"""可执行配置 freeze 的纯本地校验与复合 hash。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def runner_source_hash(root: str | Path) -> str:
    root = Path(root)
    files = {path.relative_to(root).as_posix(): _sha256(path) for path in sorted((root / "agentbench" / "live_runner").glob("*.py"))}
    return _digest(files)


def component_hashes(root: str | Path) -> dict[str, str]:
    root = Path(root)
    generation = json.loads((root / "agentbench" / "generation_metadata.json").read_text(encoding="utf-8"))
    scenario_files = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted((root / "agentbench" / "scenarios").glob("*.json"))
    }
    tool_schema_hash = _sha256(root / "agentbench/tool_schema.json")
    return {
        "agent_config_hash": _sha256(root / "agentbench/live_protocol/agent_config.yaml"),
        "evaluation_protocol_hash": _sha256(root / "agentbench/live_protocol/evaluation_protocol.yaml"),
        "seeds_hash": _sha256(root / "agentbench/live_protocol/seeds.json"),
        "prompt_hash": _sha256(root / "agentbench/live_protocol/system_prompt.md"),
        "environment_hash": _sha256(root / "agentbench/live_protocol/environment.json"),
        "provider_request_contract_hash": _sha256(root / "agentbench/live_protocol/provider_request_contract.json"),
        "scenario_hash": generation["scenario_semantic_hash"],
        "scenario_files_hash": _digest(scenario_files),
        "tool_schema_hash": generation["tool_schema_hash"],
        "tool_schema_file_hash": tool_schema_hash,
        "runner_source_hash": runner_source_hash(root),
    }


def composite_protocol_hash(root: str | Path) -> str:
    return _digest(component_hashes(root))


def validate_configuration(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    import yaml

    config = yaml.safe_load((root / "agentbench/live_protocol/agent_config.yaml").read_text(encoding="utf-8"))
    seeds = json.loads((root / "agentbench/live_protocol/seeds.json").read_text(encoding="utf-8"))
    contract = json.loads((root / "agentbench/live_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
    model = config["agent"]["model"]
    version = config["agent"]["version"]
    replicate_ids = config["sampling"]["replicate_ids"]
    passed = (
        model == contract["model_identifier"] == "gpt-5.6-sol"
        and version == contract["model_identity_semantics"] == "alias_pinned"
        and replicate_ids == seeds["replicate_ids"] == [0, 1, 2]
        and config["sampling"]["provider_seed_supported"] is False
        and seeds["provider_seed_supported"] is False
    )
    request = request_preview(root, 0)
    return {"passed": passed and request["request_contract_valid"], "model": model, "version": version, "replicate_ids": replicate_ids, "provider_seed_supported": False, "provider_request_contract_hash": _sha256(root / "agentbench/live_protocol/provider_request_contract.json"), "request_contract_valid": request["request_contract_valid"]}


def request_preview(root: str | Path, replicate_id: int) -> dict[str, Any]:
    root = Path(root)
    contract = json.loads((root / "agentbench/live_protocol/provider_request_contract.json").read_text(encoding="utf-8"))
    actions = json.loads((root / "agentbench/tool_schema.json").read_text(encoding="utf-8"))["actions"]
    tools = []
    for action in actions:
        object_fields = {"baseline_intent", "candidate_intent", "current_run", "cached_artifact", "run_result", "aggregate"}
        properties = {field: {"type": "object" if field in object_fields else "string"} for field in action["fields"]}
        tools.append({"type": "function", "name": action["type"], "description": f"Controlled ResearchCI action: {action['type']}", "parameters": {"type": "object", "properties": properties, "required": list(action["fields"]), "additionalProperties": False}, "strict": True})
    remaining_output_token_budget = 16000
    request = {"model": contract["model_identifier"], "instructions": "<frozen system prompt>", "input": "<episode input>", "temperature": contract["sampling_fields"]["temperature"], "top_p": contract["sampling_fields"]["top_p"], "max_output_tokens": min(contract["provider_per_response_output_limit"], remaining_output_token_budget), "metadata": {"replicate_id": str(replicate_id)}, "tools": tools}
    request_contract_valid = set(request) == {"model", "instructions", "input", "temperature", "top_p", "max_output_tokens", "metadata", "tools"} and all(tool["strict"] and tool["parameters"]["additionalProperties"] is False for tool in tools)
    return {"request": request, "request_contract_valid": request_contract_valid}
