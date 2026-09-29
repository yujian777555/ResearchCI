"""Experiment Contract v0.1 的 YAML 解析入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import ExperimentContract, ModelValidationError


class ContractParseError(ValueError):
    """契约文本、结构或字段无法解析。"""


class UnsupportedContractVersion(ContractParseError):
    """契约版本不是当前实现支持的版本。"""


SUPPORTED_CONTRACT_VERSION = "0.1"


def parse_contract(source: str | Path | Mapping[str, Any]) -> ExperimentContract:
    """从 YAML 文本、文件路径或已解析 mapping 加载契约。"""

    if isinstance(source, Mapping):
        raw = dict(source)
    else:
        try:
            if isinstance(source, Path):
                text = source.read_text(encoding="utf-8")
            elif isinstance(source, str) and "\n" not in source and Path(source).is_file():
                text = Path(source).read_text(encoding="utf-8")
            else:
                text = source
            raw = yaml.safe_load(text)
        except (OSError, UnicodeError, yaml.YAMLError, TypeError) as exc:
            raise ContractParseError(f"unable to parse contract: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ContractParseError("contract root must be a mapping")
    version = str(raw.get("contract_version", ""))
    if version != SUPPORTED_CONTRACT_VERSION:
        raise UnsupportedContractVersion(
            f"unsupported contract_version {version!r}; supported version is {SUPPORTED_CONTRACT_VERSION!r}"
        )
    try:
        return ExperimentContract.from_mapping(raw)
    except ModelValidationError as exc:
        raise ContractParseError(str(exc)) from exc


def load_contract(path: str | Path) -> ExperimentContract:
    """从 YAML 文件路径加载契约。"""

    return parse_contract(Path(path))
