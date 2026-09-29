from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from researchci import InvariantEngine, RunIntent, parse_contract
from researchci.schema import ContractParseError


ROOT = Path(__file__).parents[1]
FIXTURES = yaml.safe_load((ROOT / "fixtures" / "phase1b_cases.yaml").read_text(encoding="utf-8"))


def contract_mapping():
    return yaml.safe_load((ROOT / "examples" / "contract_v0_1.yaml").read_text(encoding="utf-8"))


def run(role: str, *, split_hash="split-a", epochs=10, batch_size=32, extra_config=None):
    config = {
        "training": {"max_epochs": epochs, "max_steps": 100, "batch_size": batch_size},
        "evaluation": {"max_batches": 5},
    }
    if extra_config:
        config.update(deepcopy(extra_config))
    return RunIntent(
        run_id=f"{role}-1",
        role=role,
        seed=1,
        git_commit="git-a",
        config_hash="config-a",
        dataset_hash="dataset-a",
        split_hash=split_hash,
        evaluator_hash="evaluator-a",
        environment_hash="environment-a",
        resolved_config=config,
    )


def set_path(config, path, value):
    current = config
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    if value == "missing":
        current.pop(parts[-1], None)
    else:
        current[parts[-1]] = value


def test_phase1b_schema_parses_explicit_rule_ownership():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")

    assert contract.require_same_split is True
    assert contract.equal_config_fields == ("training.batch_size",)
    assert contract.equal_budget_fields == (
        "training.max_epochs", "training.max_steps", "evaluation.max_batches"
    )


def test_phase1b_schema_rejects_budget_config_overlap():
    raw = contract_mapping()
    raw["comparison"]["equal_config_fields"].append("training.max_epochs")

    with pytest.raises(ContractParseError, match="overlap"):
        parse_contract(raw)


def test_phase1b_schema_rejects_non_boolean_split_switch():
    raw = contract_mapping()
    raw["comparison"]["require_same_split"] = "yes"

    with pytest.raises(ContractParseError, match="require_same_split"):
        parse_contract(raw)


@pytest.mark.parametrize("case", FIXTURES["c003"], ids=lambda case: case["id"])
def test_c003_fixture_matrix(case):
    raw = contract_mapping()
    raw["comparison"]["require_same_split"] = case["require_same_split"]
    baseline = run("baseline", split_hash=case["baseline_split_hash"])
    candidate = run("candidate", split_hash=case["candidate_split_hash"])
    if case["id"] == "resolved_config_split_only":
        set_path(baseline.resolved_config, "data.split_hash", case["baseline_config_split_hash"])
        set_path(candidate.resolved_config, "data.split_hash", case["candidate_config_split_hash"])

    before = deepcopy(candidate.__dict__)
    result = InvariantEngine().check_pre_run(parse_contract(raw), baseline, candidate)

    assert result.decision == case["expected_decision"]
    assert candidate.__dict__ == before
    if case["id"] == "different_split":
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert (violation.rule_id, violation.type, violation.stage, violation.location) == (
            "RCI-C003", "split_drift", "pre_run", "candidate.split_hash"
        )
        assert (violation.expected, violation.observed) == ("split-a", "split-b")
        assert violation.repair == {
            "operation": "provide_matching_split_intent",
            "path": "candidate_intent",
            "expected_split_hash": "split-a",
        }
    else:
        assert result.violations == ()


@pytest.mark.parametrize("case", FIXTURES["c004"], ids=lambda case: case["id"])
def test_c004_fixture_matrix(case):
    raw = contract_mapping()
    path = case["path"]
    if case.get("declare_equal", True):
        raw["comparison"]["equal_config_fields"] = [path]
    else:
        raw["comparison"]["equal_config_fields"] = []
    if case.get("allowed_to_change"):
        raw["comparison"]["allowed_to_change"].append(path)
    baseline = run("baseline")
    candidate = run("candidate")
    set_path(baseline.resolved_config, path, case["baseline_value"])
    set_path(candidate.resolved_config, path, case["candidate_value"])

    result = InvariantEngine().check_pre_run(parse_contract(raw), baseline, candidate)

    assert result.decision == case["expected_decision"]
    if case["id"] in {"changed_batch_size", "changed_nested_path"}:
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert (violation.rule_id, violation.type, violation.stage, violation.location) == (
            "RCI-C004", "unauthorized_config_drift", "pre_run", f"candidate.{path}"
        )
        assert (violation.expected, violation.observed) == (
            case["baseline_value"], case["candidate_value"]
        )
        assert violation.repair == {
            "operation": "set", "path": f"candidate.{path}", "value": case["baseline_value"]
        }
    elif case["id"] == "missing_declared_path":
        assert len(result.violations) == 1
        assert (result.violations[0].rule_id, result.violations[0].type) == (
            "RCI-C004", "schema_error"
        )
        assert result.violations[0].location == f"candidate.{path}"
    else:
        assert result.violations == ()


def test_c002_budget_path_is_not_owned_by_c004():
    baseline = run("baseline", epochs=10)
    candidate = run("candidate", epochs=20)

    result = InvariantEngine().check_pre_run(
        parse_contract(ROOT / "examples" / "contract_v0_1.yaml"), baseline, candidate
    )

    assert [violation.rule_id for violation in result.violations] == ["RCI-C002"]


def test_c004_does_not_infer_ownership_from_config_prefix():
    raw = contract_mapping()
    raw["comparison"]["equal_config_fields"] = ["evaluation.max_items"]
    baseline = run("baseline")
    candidate = run("candidate")
    set_path(baseline.resolved_config, "evaluation.max_items", 3)
    set_path(candidate.resolved_config, "evaluation.max_items", 4)

    result = InvariantEngine().check_pre_run(parse_contract(raw), baseline, candidate)

    assert [violation.rule_id for violation in result.violations] == ["RCI-C004"]


def test_phase1b_combined_three_rule_output_is_deterministic():
    case = FIXTURES["combined"]
    baseline = run(
        "baseline", epochs=case["baseline"]["training.max_epochs"],
        split_hash=case["baseline"]["split_hash"],
        batch_size=case["baseline"]["training.batch_size"],
    )
    candidate = run(
        "candidate", epochs=case["candidate"]["training.max_epochs"],
        split_hash=case["candidate"]["split_hash"],
        batch_size=case["candidate"]["training.batch_size"],
    )
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    engine = InvariantEngine()

    first = engine.check_pre_run(contract, baseline, candidate)
    second = engine.check_pre_run(contract, baseline, candidate)

    assert first.decision == "BLOCK"
    assert [violation.rule_id for violation in first.violations] == case["expected_rule_ids"]
    assert first.as_dict() == second.as_dict()
    assert [violation.location for violation in first.violations] == [
        "candidate.training.max_epochs", "candidate.split_hash", "candidate.training.batch_size"
    ]


def test_invalid_role_prevents_all_comparison_rules():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    baseline = run("candidate", split_hash="split-a", epochs=10, batch_size=32)
    candidate = run("candidate", split_hash="split-b", epochs=20, batch_size=64)

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "BLOCK"
    assert [violation.rule_id for violation in result.violations] == ["SCHEMA"]


def test_phase1a_contract_without_new_fields_still_parses():
    raw = contract_mapping()
    raw["comparison"].pop("require_same_split")
    raw["comparison"].pop("equal_config_fields")

    contract = parse_contract(raw)

    assert contract.require_same_split is False
    assert contract.equal_config_fields == ()
