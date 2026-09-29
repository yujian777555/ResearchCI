"""ResearchCI：面向科学可比性的最小契约检查器。"""

from .engine import InvariantEngine, check_pre_aggregate, check_pre_run
from .models import (
    AggregateIntent,
    CheckResult,
    ExperimentContract,
    ModelValidationError,
    RunIntent,
    RunResult,
    Violation,
)
from .schema import ContractParseError, UnsupportedContractVersion, load_contract, parse_contract

__all__ = [
    "AggregateIntent",
    "CheckResult",
    "ContractParseError",
    "ExperimentContract",
    "InvariantEngine",
    "ModelValidationError",
    "RunIntent",
    "RunResult",
    "UnsupportedContractVersion",
    "Violation",
    "check_pre_aggregate",
    "check_pre_run",
    "load_contract",
    "parse_contract",
]
