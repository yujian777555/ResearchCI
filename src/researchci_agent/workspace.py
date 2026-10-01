"""受控、不可越界的 agent workspace。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AgentWorkspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, relative: str | Path) -> Path:
        path = (self.root / Path(relative)).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError("workspace path escapes agent root")
        return path

    def write_text(self, relative: str | Path, content: str) -> None:
        path = self._safe(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_text(self, relative: str | Path) -> str:
        return self._safe(relative).read_text(encoding="utf-8")

    def materialize(self, files: Iterable[tuple[str, str]]) -> None:
        for relative, content in files:
            self.write_text(relative, content)

    def tree_hash(self) -> str:
        records = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                records[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return "sha256:" + hashlib.sha256(_canonical(records)).hexdigest()
