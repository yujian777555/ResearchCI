"""DS-1 结果与错误信息脱敏。"""
from __future__ import annotations
import re
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(?:DEEPSEEK_API_KEY|OPENAI_API_KEY|api[_ -]?key|authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
)

def redact_text(value: str) -> str:
    result=value
    for pattern in _SECRET_PATTERNS:
        result=pattern.sub("[REDACTED]", result)
    return result[:2000]

def redact(value: Any) -> Any:
    if isinstance(value,str): return redact_text(value)
    if isinstance(value,list): return [redact(item) for item in value]
    if isinstance(value,dict): return {key:redact(item) for key,item in value.items() if key.lower() not in {"authorization","api_key","deepseek_api_key","openai_api_key"}}
    return value
