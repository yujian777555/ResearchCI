# Experiment Contract v0.1

## 1. Purpose

ResearchCI treats experimental comparability as an executable contract.

A contract declares which properties must be identical between a baseline and candidate, which changes are explicitly permitted, which runs must exist, and which provenance fingerprints must accompany every artifact.

The v0.1 contract is intentionally narrow. It does not attempt to judge novelty, scientific importance, writing quality, citation correctness, or general research ethics.

## 2. Core model

```
Contract
  = Comparison
  + Information Flow
  + Completeness
  + Provenance
  + Cache Validity
  + Enforcement Stage
```

The first implementation must canonicalize all contract fields before evaluation so that semantically equivalent input forms do not create different rule behavior.

## 3. Canonical YAML schema

```yaml
contract_version: "0.1"

experiment:
  id: exp-001
  task: image_classification

comparison:
  baseline: baseline
  candidate: method

  require_same_split: true

  paired_seeds:
    required: true
    seeds: [1, 2, 3, 4, 5]

  equal_budget_fields:
    - training.max_epochs
    - training.max_steps
    - evaluation.max_batches

  equal_config_fields:
    - training.batch_size

  allowed_to_change:
    - model.optimizer

data:
  train_split_hash: required
  val_split_hash: required
  test_split_hash: required

metrics:
  primary:
    name: accuracy
    direction: maximize
    aggregation: mean

completeness:
  failed_runs:
    must_be_explicit: true
  aggregation:
    require_all_declared_seeds: true

provenance:
  require:
    - git_commit
    - config_hash
    - dataset_hash
    - evaluator_hash
    - environment_hash

cache:
  invalidation_keys:
    - git_commit
    - config_hash
    - dataset_hash
    - evaluator_hash

enforcement:
  pre_run: block
  pre_cache_consume: block
  pre_aggregate: block
  pre_claim: block
```

`equal_budget_fields` belongs to RCI-C002, `require_same_split` enables RCI-C003
for the top-level `RunIntent.split_hash`, and `equal_config_fields` belongs to
RCI-C004. The parser rejects a path declared in both equal field lists.
`allowed_to_change` exempts a declared equal field. If the Phase 1B fields are
absent from an older contract, split and config checks remain inactive.

For Phase 1C, `completeness.failed_runs.must_be_explicit` enables RCI-C006
run accounting, while `cache.invalidation_keys` explicitly selects the
provenance fields checked by RCI-C005. Cache provenance is never repaired by
rewriting a hash label; stale artifacts require invalidation and recomputation.

## 4. Canonical RunIntent

Every executable experiment must resolve to a canonical `RunIntent` before process launch.

```json
{
  "run_id": "candidate-seed-3",
  "role": "candidate",
  "seed": 3,
  "git_commit": "abc123",
  "config_hash": "sha256:...",
  "dataset_hash": "sha256:...",
  "split_hash": "sha256:...",
  "evaluator_hash": "sha256:...",
  "environment_hash": "sha256:...",
  "resolved_config": {
    "training": {
      "max_epochs": 100,
      "batch_size": 64
    }
  }
}
```

Requirements:
- all paths use canonical dot notation;
- hashes identify resolved inputs, not file names;
- missing required provenance is an explicit contract failure;
- roles are restricted to declared comparison roles;
- a proposed run must be validated before launch.

## 5. Canonical RunResult

```json
{
  "run_id": "candidate-seed-3",
  "status": "success",
  "metrics": {
    "accuracy": 0.841
  },
  "artifact_hash": "sha256:..."
}
```

A failed run remains a first-class `RunResult` with `status=failed`; it must not disappear from the experiment lineage.

## 6. AggregateIntent

Before aggregation, ResearchCI must receive:
- the declared comparison;
- all declared run IDs;
- all observed run results;
- the aggregation rule;
- the target metric.

This enables seed-set and failed-run completeness checks before statistics are emitted.

## 7. Enforcement lifecycle

```
Agent / User proposes run
        |
        v
   PRE-RUN CHECK
        |
        v
      execute
        |
        v
     RunResult
        |
        v
 PRE-CACHE / PRE-AGGREGATE
        |
        v
    statistics
        |
        v
   PRE-CLAIM CHECK
```

v0.1 Phase 1 implements only the checks required for RCI-C001 and RCI-C002, while keeping interfaces extensible for later stages.

## 8. Frozen v0.1 rule IDs

- `RCI-C001`: Seed-set mismatch
- `RCI-C002`: Budget mismatch
- `RCI-C003`: Dataset split drift
- `RCI-C004`: Unauthorized config drift
- `RCI-C005`: Stale cache reuse
- `RCI-C006`: Failed-run omission

Rule IDs are stable external identifiers. Do not renumber them later.

## 9. Scope boundary

ResearchCI v0.1 does not implement:
- novelty checking;
- citation verification;
- p-hacking detection;
- autonomous paper review;
- natural-language ethics judgments;
- model-selection optimization;
- an AI Scientist framework.

The project asks a narrower question:

> Can experimental comparability be enforced like software correctness?
