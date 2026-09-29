from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from researchci import (
    AggregateIntent,
    CacheConsumeIntent,
    CachedArtifactManifest,
    InvariantEngine,
    ModelValidationError,
    RunIntent,
    RunResult,
    parse_contract,
)
from researchci.schema import ContractParseError


ROOT = Path(__file__).parents[1]
FIXTURES = yaml.safe_load((ROOT / "fixtures" / "phase1c_cases.yaml").read_text(encoding="utf-8"))


def contract_mapping():
    return yaml.safe_load((ROOT / "examples" / "contract_v0_1.yaml").read_text(encoding="utf-8"))


def run(role: str, seed: int = 1, *, split_hash="split-a"):
    return RunIntent(
        run_id=f"{role}-{seed}",
        role=role,
        seed=seed,
        git_commit="git-a",
        config_hash="config-a",
        dataset_hash="dataset-a",
        split_hash=split_hash,
        evaluator_hash="evaluator-a",
        environment_hash="environment-a",
        resolved_config={
            "training": {"max_epochs": 10, "max_steps": 100, "batch_size": 32},
            "evaluation": {"max_batches": 5},
        },
    )


def result(run_id: str, status: str, *, artifact_hash="artifact-a"):
    return RunResult(
        run_id=run_id,
        status=status,
        metrics={} if status == "failed" else {"accuracy": 0.8},
        artifact_hash=None if status == "failed" else artifact_hash,
        seed=1,
        role="baseline" if run_id.startswith("baseline") else "candidate",
    )


def aggregate(
    *,
    baseline_run_ids=("baseline-1",),
    candidate_run_ids=("candidate-1",),
    observed_results=(),
    included_run_ids=(),
    reported_failed_run_ids=(),
    baseline_seed_set=(1, 2, 3),
    candidate_seed_set=(1, 2, 3),
):
    return AggregateIntent(
        experiment_id="exp-001",
        baseline_run_ids=baseline_run_ids,
        candidate_run_ids=candidate_run_ids,
        declared_seed_set=(1, 2, 3),
        aggregation_metric="accuracy",
        baseline_seed_set=baseline_seed_set,
        candidate_seed_set=candidate_seed_set,
        observed_results=observed_results,
        included_run_ids=included_run_ids,
        reported_failed_run_ids=reported_failed_run_ids,
    )


def cache_intent(*, overrides=None, omit=()):
    current = run("baseline")
    provenance = {
        "git_commit": current.git_commit,
        "config_hash": current.config_hash,
        "dataset_hash": current.dataset_hash,
        "evaluator_hash": current.evaluator_hash,
    }
    for key, value in (overrides or {}).items():
        provenance[key] = value
    for key in omit:
        provenance.pop(key, None)
    return CacheConsumeIntent(
        current_run=current,
        cached_artifact=CachedArtifactManifest(
            artifact_id="cache-123",
            artifact_hash="artifact-a",
            source_provenance=provenance,
        ),
    )


def test_phase1c_contract_fields_parse_and_backward_defaults():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    assert contract.failed_runs_must_be_explicit is True
    assert contract.cache_invalidation_keys == (
        "git_commit", "config_hash", "dataset_hash", "evaluator_hash"
    )

    raw = contract_mapping()
    raw["completeness"].pop("failed_runs")
    raw.pop("cache")
    old_contract = parse_contract(raw)
    assert old_contract.failed_runs_must_be_explicit is False
    assert old_contract.cache_invalidation_keys == ()


def test_phase1c_contract_rejects_invalid_cache_schema():
    unknown = contract_mapping()
    unknown["cache"]["invalidation_keys"].append("unknown_hash")
    with pytest.raises(ContractParseError, match="invalidation key"):
        parse_contract(unknown)

    bad_type = contract_mapping()
    bad_type["completeness"]["failed_runs"]["must_be_explicit"] = "yes"
    with pytest.raises(ContractParseError, match="must_be_explicit"):
        parse_contract(bad_type)

    duplicate = contract_mapping()
    duplicate["cache"]["invalidation_keys"].append("git_commit")
    with pytest.raises(ContractParseError, match="duplicate"):
        parse_contract(duplicate)

    null_failed_runs = contract_mapping()
    null_failed_runs["completeness"]["failed_runs"] = None
    with pytest.raises(ContractParseError, match="failed_runs"):
        parse_contract(null_failed_runs)

    null_cache = contract_mapping()
    null_cache["cache"] = None
    with pytest.raises(ContractParseError, match="cache"):
        parse_contract(null_cache)


def test_run_result_allows_null_artifact_only_for_failed_status():
    failed = result("baseline-1", "failed")
    assert failed.artifact_hash is None
    assert failed.metrics == {}

    with pytest.raises(ModelValidationError):
        RunResult(
            run_id="baseline-1",
            status="success",
            metrics={"accuracy": 0.8},
            artifact_hash=None,
        )
    with pytest.raises(ModelValidationError):
        RunResult(
            run_id="baseline-1",
            status="cancelled",
            metrics={},
            artifact_hash=None,
        )


def test_c005_matching_provenance_passes():
    result_value = InvariantEngine().check_pre_cache_consume(
        parse_contract(ROOT / "examples" / "contract_v0_1.yaml"), cache_intent()
    )
    assert result_value.decision == "PASS"
    assert result_value.violations == ()


@pytest.mark.parametrize("key", FIXTURES["c005"]["stale_keys"])
def test_c005_reports_each_stale_key_with_non_destructive_repair(key):
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    intent = cache_intent(overrides={key: f"stale-{key}"})
    before = deepcopy(intent.cached_artifact.source_provenance)

    checked = InvariantEngine().check_pre_cache_consume(contract, intent)

    assert checked.decision == "BLOCK"
    assert len(checked.violations) == 1
    violation = checked.violations[0]
    assert (violation.rule_id, violation.type, violation.stage) == (
        "RCI-C005", "stale_cache_reuse", "pre_cache_consume"
    )
    assert violation.location == f"cached_artifact.source_provenance.{key}"
    assert violation.expected == getattr(intent.current_run, key)
    assert violation.observed == f"stale-{key}"
    assert violation.repair == {
        "operation": "invalidate_and_recompute",
        "artifact_id": "cache-123",
        "mismatched_key": key,
    }
    assert intent.cached_artifact.source_provenance == before


def test_c005_returns_all_stale_keys_deterministically():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    intent = cache_intent(overrides={key: f"stale-{key}" for key in ("git_commit", "config_hash")})

    checked = InvariantEngine().check_pre_cache_consume(contract, intent)

    assert [violation.rule_id for violation in checked.violations] == ["RCI-C005", "RCI-C005"]
    assert [violation.location for violation in checked.violations] == [
        "cached_artifact.source_provenance.config_hash",
        "cached_artifact.source_provenance.git_commit",
    ]


def test_c005_ignores_undeclared_provenance_and_blocks_missing_declared_key():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    current = run("baseline")
    intent = CacheConsumeIntent(
        current_run=current,
        cached_artifact=CachedArtifactManifest(
            artifact_id="cache-123",
            artifact_hash="artifact-a",
            source_provenance={
                "git_commit": current.git_commit,
                "config_hash": current.config_hash,
                "dataset_hash": current.dataset_hash,
                "evaluator_hash": current.evaluator_hash,
                "environment_hash": "different-but-undeclared",
            },
        ),
    )
    assert InvariantEngine().check_pre_cache_consume(contract, intent).decision == "PASS"

    missing = cache_intent(omit=("config_hash",))
    checked = InvariantEngine().check_pre_cache_consume(contract, missing)
    assert checked.decision == "BLOCK"
    assert checked.violations[0].type == "schema_error"
    assert checked.violations[0].location == "cached_artifact.source_provenance.config_hash"


@pytest.mark.parametrize("case", FIXTURES["c006"], ids=lambda case: case["id"])
def test_c006_accounting_fixture_matrix(case):
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    if case["id"] == "all_success_included":
        intent = aggregate(
            observed_results=(result("baseline-1", "success"), result("candidate-1", "success")),
            included_run_ids=("baseline-1", "candidate-1"),
        )
    elif case["id"] == "failed_explicitly_reported":
        intent = aggregate(
            observed_results=(result("baseline-1", "failed"), result("candidate-1", "success")),
            included_run_ids=("candidate-1",),
            reported_failed_run_ids=("baseline-1",),
        )
    elif case["id"] == "failed_omitted":
        intent = aggregate(
            observed_results=(result("baseline-1", "failed"), result("candidate-1", "success")),
            included_run_ids=("candidate-1",),
        )
    elif case["id"] == "failed_included":
        intent = aggregate(
            observed_results=(result("baseline-1", "failed"), result("candidate-1", "success")),
            included_run_ids=("baseline-1", "candidate-1"),
        )
    elif case["id"] == "success_omitted":
        intent = aggregate(
            observed_results=(result("baseline-1", "success"), result("candidate-1", "success")),
            included_run_ids=("candidate-1",),
        )
    elif case["id"] == "declared_run_without_result":
        intent = aggregate(
            candidate_run_ids=("candidate-1", "candidate-2"),
            observed_results=(result("baseline-1", "success"), result("candidate-1", "success")),
            included_run_ids=("baseline-1", "candidate-1"),
        )
    elif case["id"] == "success_reported_failed":
        intent = aggregate(
            observed_results=(result("baseline-1", "success"), result("candidate-1", "success")),
            included_run_ids=("baseline-1", "candidate-1"),
            reported_failed_run_ids=("candidate-1",),
        )
    elif case["id"] == "unknown_accounting_id":
        intent = aggregate(
            observed_results=(result("baseline-1", "success"), result("candidate-1", "success")),
            included_run_ids=("baseline-1", "candidate-1", "unknown-1"),
        )
    else:
        intent = aggregate(
            observed_results=(result("baseline-1", "success"), result("baseline-1", "success"), result("candidate-1", "success")),
            included_run_ids=("baseline-1", "candidate-1"),
        )

    checked = InvariantEngine().check_pre_aggregate(contract, intent)
    assert checked.decision == case["expected_decision"]
    if case["id"] == "failed_omitted":
        violation = next(v for v in checked.violations if v.type == "failed_run_omission")
        assert violation.rule_id == "RCI-C006"
        assert violation.stage == "pre_aggregate"
        assert violation.location == "reported_failed_run_ids"
        assert violation.observed == ["baseline-1"]
        assert violation.repair == {
            "operation": "report_failed_run",
            "path": "reported_failed_run_ids",
            "run_id": "baseline-1",
        }


def test_c001_and_c006_accumulate_deterministically():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    intent = aggregate(
        observed_results=(result("baseline-1", "failed"), result("candidate-1", "success")),
        included_run_ids=("candidate-1",),
        baseline_seed_set=(1, 2),
        candidate_seed_set=(1, 2, 3),
    )

    checked = InvariantEngine().check_pre_aggregate(contract, intent)

    assert checked.decision == "BLOCK"
    rule_ids = [violation.rule_id for violation in checked.violations]
    assert rule_ids[0] == "RCI-C001"
    assert rule_ids[-1] == "RCI-C006"
    assert set(rule_ids) == {"RCI-C001", "RCI-C006"}


def test_c006_rejects_duplicate_accounting_ids():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    intent = aggregate(
        observed_results=(result("baseline-1", "success"), result("candidate-1", "success")),
        included_run_ids=("baseline-1", "baseline-1", "candidate-1"),
    )

    checked = InvariantEngine().check_pre_aggregate(contract, intent)

    assert checked.decision == "BLOCK"
    duplicate = next(v for v in checked.violations if v.location == "included_run_ids")
    assert duplicate.type == "run_accounting_error"


def test_phase1a_aggregate_without_accounting_fields_remains_parseable_but_active_c006_blocks_missing_records():
    contract = parse_contract(ROOT / "examples" / "contract_v0_1.yaml")
    intent = aggregate(observed_results=(), included_run_ids=(), reported_failed_run_ids=())

    checked = InvariantEngine().check_pre_aggregate(contract, intent)

    assert checked.decision == "BLOCK"
    assert any(violation.rule_id == "RCI-C006" for violation in checked.violations)
