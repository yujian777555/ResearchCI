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


_HISTORICAL_RUNNER_FILES = ("__init__.py", "budget.py", "dry_run.py", "freeze.py", "interfaces.py")


def runner_source_hash(root: str | Path, *, include_new: bool = True) -> str:
    root = Path(root)
    runner = root / "agentbench" / "live_runner"
    paths = sorted(runner.glob("*.py")) if include_new else [runner / name for name in _HISTORICAL_RUNNER_FILES if (runner / name).exists()]
    files = {path.relative_to(root).as_posix(): _sha256(path) for path in paths}
    return _digest(files)


def _base_component_hashes(root: Path, *, include_new_runner: bool) -> dict[str, str]:
    generation = json.loads((root / "agentbench" / "generation_metadata.json").read_text(encoding="utf-8"))
    scenario_files = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted((root / "agentbench" / "scenarios").glob("*.json"))
    }
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
        "tool_schema_file_hash": _sha256(root / "agentbench/tool_schema.json"),
        "runner_source_hash": runner_source_hash(root, include_new=include_new_runner),
    }


def component_hashes(root: str | Path) -> dict[str, str]:
    """返回 Phase 2B-1 历史语义所需的组件视图。"""
    root_path = Path(root)
    result = _base_component_hashes(root_path, include_new_runner=False)
    # 历史报告必须保持原有含义，即使当前 checkout 已增加 Phase 2B-2A 文件。
    historical = root_path / "agentbench/reports/phase2b1_freeze.json"
    if historical.exists():
        stored = json.loads(historical.read_text(encoding="utf-8")).get("runner_source_hash")
        if stored:
            result["runner_source_hash"] = stored
    return result


def execution_component_hashes(root: str | Path) -> dict[str, str]:
    """返回包含 Phase 2B-2A 新 runner 源码的执行协议组件。"""
    return _base_component_hashes(Path(root), include_new_runner=True)


def composite_protocol_hash(root: str | Path) -> str:
    return _digest(component_hashes(root))


def execution_protocol_hash(components: dict[str, str]) -> str:
    return _digest(components)


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


def request_preview(root: str | Path, replicate_id: int, *, remaining_output_token_budget: int = 16000) -> dict[str, Any]:
    from agentbench.live_adapter.openai_responses import ResponsesRequestBuilder

    builder = ResponsesRequestBuilder(root, system_prompt="<frozen system prompt>")
    request = builder.build(agent_visible_context="<episode input>", replicate_id=replicate_id, remaining_output_token_budget=remaining_output_token_budget)
    request_contract_valid = (
        set(request) == {"model", "instructions", "input", "temperature", "top_p", "max_output_tokens", "metadata", "tools"}
        and all(tool["strict"] and tool["parameters"]["additionalProperties"] is False for tool in request["tools"])
        and all("seed" not in tool and "max_tool_calls" not in tool for tool in request["tools"])
    )
    return {"request": request, "request_contract_valid": request_contract_valid}
