"""Benchmark canonical serialization and hashing helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def tree_hash(root: Path, *, excluded_names: set[str] | None = None) -> str:
    excluded_names = excluded_names or set()
    records: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in excluded_names:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        records.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return sha256_value(records)


def opaque_case_id(fields: Any) -> str:
    return "case_" + hashlib.sha256(canonical_bytes(fields)).hexdigest()[:12]
