from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from researchci.engine import InvariantEngine
from researchci.models import (
    AggregateIntent,
    ExperimentContract,
    ModelValidationError,
    RunIntent,
)
from researchci.schema import (
    ContractParseError,
    UnsupportedContractVersion,
    parse_contract,
)


ROOT = Path(__file__).parents[1]


CONTRACT_YAML = """
contract_version: "0.1"
experiment:
  id: exp-001
  task: image_classification
comparison:
  baseline: baseline
  candidate: candidate
  paired_seeds:
    required: true
    seeds: [1, 2, 3]
  equal_budget_fields:
    - training.max_epochs
    - training.max_steps
    - evaluation.max_batches
    - training.batch_size
  allowed_to_change:
    - training.batch_size
completeness:
  aggregation:
    require_all_declared_seeds: true
metrics:
  primary:
    name: accuracy
    direction: maximize
    aggregation: mean
"""


def make_run(role: str, seed: int, *, epochs=10, steps=100, eval_batches=5, batch_size=32):
    return RunIntent(
        run_id=f"{role}-{seed}",
        role=role,
        seed=seed,
        git_commit="sha-git",
        config_hash="sha-config",
        dataset_hash="sha-data",
        split_hash="sha-split",
        evaluator_hash="sha-evaluator",
        environment_hash="sha-env",
        resolved_config={
            "training": {
                "max_epochs": epochs,
                "max_steps": steps,
                "batch_size": batch_size,
            },
            "evaluation": {"max_batches": eval_batches},
        },
    )


def make_aggregate(baseline_seeds=(1, 2, 3), candidate_seeds=(1, 2, 3)):
    return AggregateIntent(
        experiment_id="exp-001",
        baseline_run_ids=tuple(f"baseline-{seed}" for seed in baseline_seeds),
        candidate_run_ids=tuple(f"candidate-{seed}" for seed in candidate_seeds),
        declared_seed_set=(1, 2, 3),
        aggregation_metric="accuracy",
        baseline_seed_set=baseline_seeds,
        candidate_seed_set=candidate_seeds,
    )


def test_contract_parser_loads_v01_yaml_and_canonicalizes_paths():
    contract = parse_contract(CONTRACT_YAML)

    assert isinstance(contract, ExperimentContract)
    assert contract.contract_version == "0.1"
    assert contract.experiment_id == "exp-001"
    assert contract.paired_seeds == (1, 2, 3)
    assert contract.equal_budget_fields == (
        "training.max_epochs",
        "training.max_steps",
        "evaluation.max_batches",
        "training.batch_size",
    )


def test_contract_parser_rejects_unsupported_version():
    with pytest.raises(UnsupportedContractVersion):
        parse_contract(CONTRACT_YAML.replace('"0.1"', '"0.2"'))


def test_contract_parser_rejects_malformed_yaml():
    with pytest.raises(ContractParseError):
        parse_contract("contract_version: [")


def test_contract_parser_rejects_missing_active_rule_fields():
    missing_comparison = CONTRACT_YAML.replace(
        "  equal_budget_fields:\n    - training.max_epochs\n    - training.max_steps\n    - evaluation.max_batches\n    - training.batch_size\n",
        "",
    )
    with pytest.raises(ContractParseError):
        parse_contract(missing_comparison)


def test_contract_parser_rejects_retired_equal_fields_name():
    retired_name = CONTRACT_YAML.replace("equal_budget_fields:", "equal_fields:")

    with pytest.raises(ContractParseError):
        parse_contract(retired_name)


def test_contract_parser_rejects_missing_seed_completeness_semantics():
    missing_completeness = CONTRACT_YAML.replace(
        "completeness:\n  aggregation:\n    require_all_declared_seeds: true\n", ""
    )

    with pytest.raises(ContractParseError):
        parse_contract(missing_completeness)


def test_run_intent_requires_canonical_provenance_and_config():
    run = make_run("baseline", 1)
    assert run.seed == 1
    assert run.resolved_config["training"]["max_epochs"] == 10

    with pytest.raises(ModelValidationError):
        RunIntent(
            run_id="bad",
            role="baseline",
            seed=1,
            git_commit="",
            config_hash="sha-config",
            dataset_hash="sha-data",
            split_hash="sha-split",
            evaluator_hash="sha-evaluator",
            environment_hash="sha-env",
            resolved_config={},
        )


def test_pre_aggregate_valid_exact_paired_seeds_passes():
    result = InvariantEngine().check_pre_aggregate(parse_contract(CONTRACT_YAML), make_aggregate())

    assert result.decision == "PASS"
    assert result.violations == ()


@pytest.mark.parametrize(
    ("baseline", "candidate", "location", "repair_operation", "repair_seeds"),
    [
        ((1, 2), (1, 2, 3), "baseline.seed_set", "add", [3]),
        ((1, 2, 3), (1, 2), "candidate.seed_set", "add", [3]),
        ((1, 2, 3), (1, 2, 4), "candidate.seed_set", "remove", [4]),
    ],
)
def test_c001_reports_missing_or_extra_seeds_with_machine_repair(
    baseline, candidate, location, repair_operation, repair_seeds
):
    result = InvariantEngine().check_pre_aggregate(
        parse_contract(CONTRACT_YAML), make_aggregate(baseline, candidate)
    )

    assert result.decision == "BLOCK"
    assert any(v.rule_id == "RCI-C001" and v.stage == "pre_aggregate" for v in result.violations)
    violation = next(v for v in result.violations if v.location == location)
    assert violation.repair == {
        "operation": repair_operation,
        "path": location,
        "seeds": repair_seeds,
    }


def test_c001_reports_baseline_candidate_set_difference():
    result = InvariantEngine().check_pre_aggregate(
        parse_contract(CONTRACT_YAML), make_aggregate((1, 2, 3), (1, 2, 4))
    )

    mismatch = next(v for v in result.violations if v.location == "comparison.paired_seed_set")
    assert mismatch.rule_id == "RCI-C001"
    assert mismatch.location == "comparison.paired_seed_set"
    assert mismatch.repair["operation"] == "align"
    assert mismatch.repair["path"] == "candidate.seed_set"


def test_c001_missing_observed_seed_sets_is_explicit_schema_error():
    aggregate = AggregateIntent(
        experiment_id="exp-001",
        baseline_run_ids=("baseline-1",),
        candidate_run_ids=("candidate-1",),
        declared_seed_set=(1, 2, 3),
        aggregation_metric="accuracy",
    )
    result = InvariantEngine().check_pre_aggregate(parse_contract(CONTRACT_YAML), aggregate)

    assert result.decision == "BLOCK"
    assert any(v.type == "schema_error" for v in result.violations)


def test_pre_run_equal_budgets_pass_and_allowed_change_does_not_false_block():
    contract = parse_contract(CONTRACT_YAML)
    baseline = make_run("baseline", 1)
    candidate = make_run("candidate", 1)

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "PASS"
    assert result.violations == ()


def test_official_example_with_identical_intents_passes_pre_run():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")

    result = InvariantEngine().check_pre_run(
        contract,
        make_run("baseline", 1),
        make_run("candidate", 1),
    )

    assert result.decision == "PASS"
    assert result.violations == ()


def test_non_budget_split_and_metric_changes_are_not_owned_by_c002():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    baseline = make_run("baseline", 1)
    candidate = make_run("candidate", 1)
    baseline.resolved_config["data"] = {"split_hash": "split-a"}
    candidate.resolved_config["data"] = {"split_hash": "split-b"}
    baseline.resolved_config["evaluation"]["primary_metric"] = "accuracy"
    candidate.resolved_config["evaluation"]["primary_metric"] = "f1"

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "PASS"
    assert all(violation.rule_id != "RCI-C002" for violation in result.violations)


@pytest.mark.parametrize(
    ("baseline_role", "candidate_role", "location", "expected", "observed", "intent_path"),
    [
        ("candidate", "candidate", "baseline.role", "baseline", "candidate", "baseline_intent"),
        ("baseline", "baseline", "candidate.role", "candidate", "baseline", "candidate_intent"),
    ],
)
def test_pre_run_role_mismatch_is_schema_error_before_c002(
    baseline_role, candidate_role, location, expected, observed, intent_path
):
    contract = parse_contract(CONTRACT_YAML)
    baseline = make_run(baseline_role, 1, epochs=10)
    candidate = make_run(candidate_role, 1, epochs=20)

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "BLOCK"
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.rule_id == "SCHEMA"
    assert violation.type == "schema_error"
    assert violation.stage == "pre_run"
    assert violation.location == location
    assert violation.expected == expected
    assert violation.observed == observed
    assert violation.repair == {
        "operation": "provide_matching_intent",
        "path": intent_path,
        "expected_role": expected,
    }
    assert ".role" not in violation.repair["path"]
    assert baseline.role == baseline_role
    assert candidate.role == candidate_role


def test_exact_swapped_intents_use_non_destructive_swap_repair():
    contract = parse_contract(CONTRACT_YAML)
    baseline_intent = make_run("candidate", 1, epochs=10)
    candidate_intent = make_run("baseline", 1, epochs=20)

    result = InvariantEngine().check_pre_run(contract, baseline_intent, candidate_intent)

    assert result.decision == "BLOCK"
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.location == "comparison.roles"
    assert violation.repair == {
        "operation": "swap_intents",
        "paths": ["baseline_intent", "candidate_intent"],
    }
    assert violation.repair["operation"] != "set"
    assert baseline_intent.role == "candidate"
    assert candidate_intent.role == "baseline"


def test_unresolvable_role_mismatch_requires_manual_resolution():
    contract = parse_contract(CONTRACT_YAML)
    baseline_intent = make_run("unknown-a", 1)
    candidate_intent = make_run("unknown-b", 1)

    result = InvariantEngine().check_pre_run(contract, baseline_intent, candidate_intent)

    assert result.decision == "BLOCK"
    assert len(result.violations) == 2
    assert {v.repair["operation"] for v in result.violations} == {
        "manual_resolution_required"
    }
    assert all("role" not in v.repair.get("path", "") for v in result.violations)


@pytest.mark.parametrize(
    ("field", "baseline_value", "candidate_value"),
    [
        ("training.max_epochs", 10, 20),
        ("training.max_steps", 100, 200),
        ("evaluation.max_batches", 5, 7),
    ],
)
def test_c002_blocks_each_declared_budget_path(field, baseline_value, candidate_value):
    contract = parse_contract(CONTRACT_YAML)
    baseline = make_run("baseline", 1)
    candidate = make_run("candidate", 1)
    baseline_config = dict(baseline.resolved_config)
    candidate_config = dict(candidate.resolved_config)
    section, key = field.split(".")
    baseline_section = dict(baseline_config[section])
    candidate_section = dict(candidate_config[section])
    baseline_section[key] = baseline_value
    candidate_section[key] = candidate_value
    baseline_config[section] = baseline_section
    candidate_config[section] = candidate_section
    argument = {
        "training.max_epochs": "epochs",
        "training.max_steps": "steps",
        "evaluation.max_batches": "eval_batches",
    }[field]
    baseline = make_run("baseline", 1, **{argument: baseline_value})
    candidate = make_run("candidate", 1, **{argument: candidate_value})

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "BLOCK"
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.rule_id == "RCI-C002"
    assert violation.type == "budget_mismatch"
    assert violation.stage == "pre_run"
    assert violation.location == f"candidate.{field}"
    assert violation.expected == baseline_value
    assert violation.observed == candidate_value
    assert violation.repair == {
        "operation": "set",
        "path": f"candidate.{field}",
        "value": baseline_value,
    }


def test_c002_skips_a_changed_allowed_field():
    contract = parse_contract(CONTRACT_YAML)
    result = InvariantEngine().check_pre_run(
        contract,
        make_run("baseline", 1, batch_size=32),
        make_run("candidate", 1, batch_size=128),
    )

    assert result.decision == "PASS"


def test_c002_missing_declared_path_is_explicit_schema_error():
    contract = parse_contract(CONTRACT_YAML)
    baseline = make_run("baseline", 1)
    candidate = make_run("candidate", 1)
    candidate.resolved_config["training"].pop("max_steps")

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "BLOCK"
    assert result.violations[0].rule_id == "RCI-C002"
    assert result.violations[0].type == "schema_error"
    assert result.violations[0].location == "candidate.training.max_steps"


def test_c002_returns_all_declared_budget_violations():
    contract = parse_contract(CONTRACT_YAML)
    baseline = make_run("baseline", 1, epochs=10, steps=100, eval_batches=5)
    candidate = make_run("candidate", 1, epochs=20, steps=200, eval_batches=7)

    result = InvariantEngine().check_pre_run(contract, baseline, candidate)

    assert result.decision == "BLOCK"
    assert [violation.location for violation in result.violations] == [
        "candidate.evaluation.max_batches",
        "candidate.training.max_epochs",
        "candidate.training.max_steps",
    ]


def test_stage_specific_engine_never_runs_c001_during_pre_run_or_c002_during_pre_aggregate():
    engine = InvariantEngine()
    contract = parse_contract(CONTRACT_YAML)
    baseline = make_run("baseline", 1, epochs=10)
    candidate = make_run("candidate", 1, epochs=20)

    pre_run = engine.check_pre_run(contract, baseline, candidate)
    pre_aggregate = engine.check_pre_aggregate(contract, make_aggregate((1, 2), (1, 2, 3)))

    assert all(v.rule_id == "RCI-C002" for v in pre_run.violations)
    assert all(v.rule_id == "RCI-C001" for v in pre_aggregate.violations)


def test_violation_ordering_is_deterministic_and_check_result_is_serializable():
    contract = parse_contract(CONTRACT_YAML)
    aggregate = make_aggregate((1, 2), (1, 4))
    first = InvariantEngine().check_pre_aggregate(contract, aggregate)
    second = InvariantEngine().check_pre_aggregate(contract, aggregate)

    assert first.as_dict() == second.as_dict()
    assert [v.location for v in first.violations] == sorted(
        v.location for v in first.violations
    )
    assert first.as_dict()["decision"] == "BLOCK"
    assert all(set(v.as_dict()) == {
        "rule_id", "type", "stage", "location", "message", "expected", "observed", "repair"
    } for v in first.violations)


def test_example_contract_file_is_parseable():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    assert contract.contract_version == "0.1"


def test_phase1a_fixture_matrix_declares_all_required_cases():
    matrix = yaml.safe_load((ROOT / "fixtures" / "phase1a_cases.yaml").read_text(encoding="utf-8"))

    assert matrix["contract_fields"] == {
        "equal_budget_fields": [
            "training.max_epochs",
            "training.max_steps",
            "evaluation.max_batches",
        ],
        "excluded_from_c002": ["data.split_hash", "evaluation.primary_metric"],
    }
    assert {case["id"] for case in matrix["c001"]} == {
        "valid_paired_seeds",
        "candidate_missing_seed",
        "different_seed_sets",
        "unexpected_extra_seed",
    }
    assert {case["id"] for case in matrix["c002"]} == {
        "equal_max_epochs",
        "mismatched_max_epochs",
        "mismatched_max_steps",
        "mismatched_evaluation_budget",
        "allowed_field_changed",
    }
