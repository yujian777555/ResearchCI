"""Provider strict tool schema 校验与 domain payload 兼容转换。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


class ToolSchemaValidationError(ValueError):
    """工具 payload 不符合冻结 schema。"""


def _types(schema: Mapping[str, Any]) -> set[str]:
    value = schema.get("type")
    return set(value) if isinstance(value, list) else ({value} if value else set())


def _accepts_null(schema: Mapping[str, Any]) -> bool:
    return "null" in _types(schema)


def strict_schema_issues(schema: Mapping[str, Any], path: str = "schema") -> list[str]:
    """递归检查 Responses strict function calling 的 object 约束。"""
    issues: list[str] = []
    types = _types(schema)
    if "object" in types:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if schema.get("additionalProperties") is not False:
            issues.append(f"{path}: additionalProperties must be false")
        if set(properties) != set(required):
            issues.append(f"{path}: required must exactly match properties")
        for name, child in properties.items():
            issues.extend(strict_schema_issues(child, f"{path}.properties.{name}"))
    if "array" in types and "items" in schema:
        issues.extend(strict_schema_issues(schema["items"], f"{path}.items"))
    for key in ("oneOf", "anyOf", "allOf"):
        for index, branch in enumerate(schema.get(key, [])):
            issues.extend(strict_schema_issues(branch, f"{path}.{key}[{index}]"))
    return issues


def validate_provider_tool_schemas(tool_schemas: list[dict[str, Any]]) -> None:
    issues = []
    for action in tool_schemas:
        issues.extend(strict_schema_issues(action["parameters"], f"tool[{action['type']}].parameters"))
    if issues:
        raise ToolSchemaValidationError("; ".join(issues))


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object": return isinstance(value, dict)
    if expected == "array": return isinstance(value, list)
    if expected == "string": return isinstance(value, str)
    if expected == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean": return isinstance(value, bool)
    if expected == "null": return value is None
    return False


def validate_json_schema(schema: Mapping[str, Any], value: Any, path: str = "payload") -> None:
    types = _types(schema)
    if types and not any(_type_matches(value, item) for item in types):
        raise ToolSchemaValidationError(f"{path} has invalid type")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolSchemaValidationError(f"{path} has invalid enum value")
    if value is None:
        return
    if "object" in types and isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing: raise ToolSchemaValidationError(f"{path} missing required fields: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown: raise ToolSchemaValidationError(f"{path} contains unknown fields: {', '.join(unknown)}")
        for name, child in properties.items():
            if name in value: validate_json_schema(child, value[name], f"{path}.{name}")
    if "array" in types and isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value): validate_json_schema(schema["items"], item, f"{path}[{index}]")


def _fill_nullable(schema: Mapping[str, Any], value: Any) -> Any:
    if value is None:
        return None
    types = _types(schema)
    if "object" in types and isinstance(value, dict):
        output = deepcopy(value)
        for name, child in schema.get("properties", {}).items():
            if name not in output and _accepts_null(child):
                output[name] = None
            elif name in output:
                output[name] = _fill_nullable(child, output[name])
        return output
    if "array" in types and isinstance(value, list) and "items" in schema:
        return [_fill_nullable(schema["items"], item) for item in value]
    return deepcopy(value)


def _strip_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_nulls(item) for item in value]
    return value


def normalize_domain_payload(tool_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """移除 provider strict 表示中补入的 nullable 缺省字段。"""
    output = deepcopy(dict(payload))
    def clean_intent(intent: Any) -> Any:
        if isinstance(intent, dict) and "resolved_config" in intent:
            intent["resolved_config"] = _strip_nulls(intent["resolved_config"])
        return intent
    if tool_name == "run_experiment":
        for key in ("baseline_intent", "candidate_intent"):
            if key in output: output[key] = clean_intent(output[key])
        for key in ("baseline_intents", "candidate_intents"):
            if output.get(key) is None: output.pop(key, None)
            elif isinstance(output.get(key), list): output[key] = [clean_intent(item) for item in output[key]]
    elif tool_name == "consume_cache":
        if isinstance(output.get("current_run"), dict): output["current_run"] = clean_intent(output["current_run"])
        artifact = output.get("cached_artifact")
        if isinstance(artifact, dict) and isinstance(artifact.get("source_provenance"), dict):
            artifact["source_provenance"] = _strip_nulls(artifact["source_provenance"])
    elif tool_name == "propose_aggregate":
        aggregate = output.get("aggregate")
        if isinstance(aggregate, dict):
            for key in ("baseline_seed_set", "candidate_seed_set", "baseline_runs", "candidate_runs", "observed_results", "included_run_ids", "reported_failed_run_ids"):
                if aggregate.get(key) is None: aggregate.pop(key, None)
            for key in ("baseline_runs", "candidate_runs"):
                if isinstance(aggregate.get(key), list): aggregate[key] = [clean_intent(item) for item in aggregate[key]]
    return output


def prepare_provider_payload(tool_name: str, payload: Mapping[str, Any], tool_schemas: list[dict[str, Any]]) -> dict[str, Any]:
    for action in tool_schemas:
        if action["type"] == tool_name:
            return _fill_nullable(action["parameters"], dict(payload))
    raise ToolSchemaValidationError(f"unknown tool: {tool_name}")


def validate_tool_payload(tool_name: str, payload: Mapping[str, Any], tool_schemas: list[dict[str, Any]]) -> dict[str, Any]:
    provider_payload = prepare_provider_payload(tool_name, payload, tool_schemas)
    action = next((item for item in tool_schemas if item["type"] == tool_name), None)
    if action is None: raise ToolSchemaValidationError(f"unknown tool: {tool_name}")
    validate_json_schema(action["parameters"], provider_payload)
    return normalize_domain_payload(tool_name, provider_payload)
