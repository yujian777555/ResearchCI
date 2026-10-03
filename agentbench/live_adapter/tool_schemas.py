"""由 ResearchCI domain model 推导的 strict tool payload schema。"""

from __future__ import annotations

from typing import Any, Mapping


class ToolSchemaValidationError(ValueError):
    """工具 payload 不符合冻结 schema。"""


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
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_type_matches(value, item) for item in expected):
            raise ToolSchemaValidationError(f"{path} has invalid type")
    elif expected is not None and not _type_matches(value, expected):
        raise ToolSchemaValidationError(f"{path} has invalid type")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolSchemaValidationError(f"{path} has invalid enum value")
    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing: raise ToolSchemaValidationError(f"{path} missing required fields: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown: raise ToolSchemaValidationError(f"{path} contains unknown fields: {', '.join(unknown)}")
        for name, child in properties.items():
            if name in value: validate_json_schema(child, value[name], f"{path}.{name}")
    if expected == "array" and isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value): validate_json_schema(schema["items"], item, f"{path}[{index}]")


def validate_tool_payload(tool_name: str, payload: Mapping[str, Any], tool_schemas: list[dict[str, Any]]) -> None:
    for action in tool_schemas:
        if action["type"] == tool_name:
            validate_json_schema(action["parameters"], dict(payload))
            return
    raise ToolSchemaValidationError(f"unknown tool: {tool_name}")
