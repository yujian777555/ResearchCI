"""稳定序列化、科学输入 diff 与生成树哈希。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


UNORDERED_FIELDS = {
    "seeds", "baseline_seed_set", "candidate_seed_set", "declared_seed_set",
    "baseline_run_ids", "candidate_run_ids", "included_run_ids", "reported_failed_run_ids",
    "equal_budget_fields", "equal_config_fields", "allowed_to_change", "invalidation_keys",
    "expected_rule_ids", "expected_locations", "changed_paths", "allowed_changed_paths",
}
DERIVED_FILES = {"generation_metadata.json", "integrity_report.json", "integrity_report.md", "reproducibility_report.json"}


def canonicalize(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: canonicalize(item, key) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        items = [canonicalize(item) for item in value]
        if items and all(isinstance(item, dict) and "run_id" in item for item in items):
            return sorted(items, key=lambda item: (item["run_id"], json.dumps(item, sort_keys=True)))
        if field in UNORDERED_FIELDS:
            return sorted(items)
        return items
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(canonicalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def file_hash_map(root: Path, *, deterministic_only: bool = False) -> dict[str, str]:
    records = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if deterministic_only and (path.name in DERIVED_FILES or relative.startswith("reports/")):
            continue
        records[relative] = sha256_bytes(path.read_bytes())
    return records


def tree_hash(root: Path, *, excluded_names: set[str] | None = None) -> str:
    records = file_hash_map(root, deterministic_only=True)
    if excluded_names:
        records = {name: value for name, value in records.items() if Path(name).name not in excluded_names}
    return sha256_value(records)


def opaque_case_id(fields: Any) -> str:
    return "case_" + hashlib.sha256(canonical_bytes(fields)).hexdigest()[:12]


def canonical_diff(before: Any, after: Any, path: str = "") -> list[dict]:
    before, after = canonicalize(before), canonicalize(after)
    if before == after:
        return []
    if isinstance(before, list) and isinstance(after, list) and all(isinstance(item, dict) and "run_id" in item for item in before + after):
        before = {item["run_id"]: item for item in before}
        after = {item["run_id"]: item for item in after}
    if isinstance(before, dict) and isinstance(after, dict):
        changed = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else key
            if key not in before or key not in after:
                changed.append({"path": child, "before": before.get(key), "after": after.get(key), "before_present": key in before, "after_present": key in after})
            else:
                changed.extend(canonical_diff(before[key], after[key], child))
        return changed
    return [{"path": path, "before": before, "after": after, "before_present": True, "after_present": True}]


def get_path(config: dict, path: str) -> Any:
    for part in path.split("."):
        config = config[part]
    return config


def set_path(config: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        config = config[part]
    config[parts[-1]] = value
