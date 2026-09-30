# Phase 1D Plan — ExpContractBench v0.1 Deterministic Generator + Evaluation Harness

Status: **Planner-frozen for implementation**

Depends on:
- Phase 1A accepted
- Phase 1B accepted
- Phase 1C accepted at commit `316d4897aa07c5eedf27709ca049e6e14b1b2316`
- `docs/EXPCONTRACTBENCH_V0_1.md`
- `docs/MVP_EXPERIMENT_PROTOCOL.md`

## 1. Goal

Build the first complete deterministic benchmark infrastructure for the six frozen ResearchCI rules.

Phase 1D must deliver:

1. three controlled repository profiles;
2. deterministic clean base cases;
3. six versioned mutation injectors;
4. exactly 240 benchmark cases under the frozen v0.1 design;
5. independent benchmark-integrity validation;
6. an evaluation harness that can run ResearchCI without exposing ground truth to the system under test;
7. metrics and machine-readable result reports.

Phase 1D is benchmark engineering.

It must **not**:
- change C001-C006 semantics;
- add C007+;
- start Agent stress testing;
- tune ResearchCI against the locked split;
- introduce learned/LLM components.

The six-rule engine is frozen while this benchmark is constructed.

## 2. Frozen benchmark cardinality

The v0.1 benchmark contains exactly:

```
3 repository profiles
x 6 violation classes
x 10 invalid variants
= 180 invalid cases

3 repository profiles
x 20 valid controls
= 60 valid cases

TOTAL = 240 cases
```

Rule distribution must be exactly:

- RCI-C001: 30 invalid cases
- RCI-C002: 30 invalid cases
- RCI-C003: 30 invalid cases
- RCI-C004: 30 invalid cases
- RCI-C005: 30 invalid cases
- RCI-C006: 30 invalid cases

Each repository contributes:
- 60 invalid;
- 20 valid;
- 80 total.

## 3. Development / locked split

Freeze a 50/50 split now.

### Invalid cases

Each repo/rule pair has mutation seeds `0..9`.

- seeds `0..4` -> `dev`
- seeds `5..9` -> `locked`

Therefore:
- 90 invalid dev cases;
- 90 invalid locked cases.

### Valid cases

Each repository has valid-control indices `0..19`.

- indices `0..9` -> `dev`
- indices `10..19` -> `locked`

Therefore:
- 30 valid dev cases;
- 30 valid locked cases.

Totals:

```
dev    = 120
locked = 120
total  = 240
```

The runner must default to `dev`.

A locked evaluation requires an explicit flag and is not part of ordinary Phase 1D development runs.

## 4. Frozen repository profiles

Use three benchmark-owned, deterministic, CPU-friendly repository fixtures:

1. `tabular_sklearn`
2. `vision_pytorch`
3. `text_classification`

These are **controlled repository profiles**, not claims of real-world repository generalization.

Each fixture should contain enough realistic structure to produce:
- a contract;
- baseline/candidate resolved configs;
- run intents;
- cache provenance;
- aggregate/run-result evidence.

No model training is required in Phase 1D.

The fixture may contain tiny representative code/config/data-manifest files, but benchmark generation must not require network downloads.

Real repository generalization remains Phase 3.

## 5. Benchmark package separation

Implement the benchmark as a separate package/module boundary, e.g.:

```
src/expcontractbench/
  __init__.py
  schema.py
  canonical.py
  profiles.py
  generator.py
  validator.py
  runner.py
  metrics.py
  injectors/
    __init__.py
    c001_seed_set.py
    c002_budget.py
    c003_split.py
    c004_config.py
    c005_cache.py
    c006_failed_run.py
  adapters/
    __init__.py
    researchci_runtime.py
    no_check.py

benchmarks/expcontractbench_v0_1/
  repos/
    tabular_sklearn/
    vision_pytorch/
    text_classification/
  manifests/
  README.md

tests/
  test_expcontractbench_*.py
```

Equivalent organization is acceptable if benchmark code is clearly separated from `researchci.rules`.

## 6. Core rule-engine freeze

During Phase 1D, do not edit the scientific semantics of:

- `src/researchci/rules/**`
- lifecycle ownership of C001-C006
- contract semantics that determine those rules

If benchmark construction reveals a core-rule defect:
- stop;
- preserve the failing case;
- report it to Planner;
- do not alter the benchmark to make ResearchCI pass;
- do not silently patch the engine.

Non-semantic serialization/helper additions require explicit justification in the completion report.

## 7. Canonical case model

Every generated case must have a canonical machine-readable manifest.

Required fields:

```json
{
  "benchmark_version": "0.1",
  "case_id": "opaque-stable-id",
  "split": "dev",
  "repo_id": "tabular_sklearn",
  "repo_fixture_version": "0.1",
  "base_valid_case_id": "opaque-valid-id",
  "label": "invalid",
  "target_rule_id": "RCI-C002",
  "target_stage": "pre_run",
  "expected_decision": "BLOCK",
  "expected_rule_ids": ["RCI-C002"],
  "expected_locations": ["candidate.training.max_epochs"],
  "mutation": {
    "operator": "budget_field_change",
    "operator_version": "0.1",
    "seed": 3,
    "parameters": {}
  },
  "declared_cost_units": 100,
  "input_tree_hash": "sha256:..."
}
```

Valid controls use:
- `label = valid`;
- `target_rule_id = null`;
- `expected_decision = PASS`;
- `expected_rule_ids = []`.

Ground-truth metadata must never be passed to the checker adapter.

## 8. Opaque case IDs

Do not encode the violation name/rule in the case ID.

Generate a stable opaque ID from a canonical hash over fields such as:

```
benchmark_version
repo_id
base_valid_case_id
mutation operator/version/seed
split
```

Example shape:

`case_4f91c6d7e2a1`

The system under test must not receive:
- target rule ID;
- mutation operator name;
- expected action;
- ground-truth location;
- label.

## 9. Base valid controls

Create 20 deterministic valid controls per repository.

Every valid base must PASS every lifecycle input it contains:

- pre-run;
- pre-cache-consume;
- pre-aggregate.

Invalid cases are derived from valid controls and keep a `base_valid_case_id`.

Multiple invalid cases may derive from the same valid control.

A base control used for an invalid mutation must be in the same dev/locked split as the invalid case.

## 10. Independent ground truth — no circular labels

This is mandatory.

The benchmark generator/validator must **not call ResearchCI to decide whether a case is valid or what its rule label is**.

Ground truth comes from:
- the chosen injector;
- explicit mutation semantics;
- independent structural postconditions.

Each injector implements the conceptual equivalent of:

```python
mutated, mutation_manifest = inject(base_case, seed)
validate_target_postcondition(base_case, mutated, mutation_manifest)
validate_non_target_invariants(base_case, mutated, mutation_manifest)
```

These validators must not invoke:
- `InvariantEngine`;
- C001-C006 rule functions;
- ResearchCI decisions.

ResearchCI may be run later by the evaluation harness, but it is not an oracle for benchmark creation.

## 11. Single-target invalid cases

Every primary invalid case must target exactly one rule ID.

The mutation validator must guarantee:
- the intended target condition was introduced;
- non-target scientific dimensions remain valid;
- expected rule ID is exactly one of C001-C006.

ResearchCI may emit multiple violation records under the same rule ID where the mutation intentionally affects multiple owned fields, but a v0.1 primary case must not intentionally create a second rule class.

If an injector cannot isolate its rule from other rules, treat that as a benchmark-design failure, not a reason to weaken expected ground truth.

## 12. C001 injector

Target: `RCI-C001`, stage `pre_aggregate`.

Inject paired-seed comparability failures while keeping C006 run accounting internally valid.

Examples across the 10 variants:
- baseline evidence missing one contracted seed;
- candidate evidence missing one contracted seed;
- baseline/candidate evidence sets differ;
- one side contains an extra undeclared seed.

Important:
- actual run evidence must drive the mismatch;
- do not create the old free-standing seed-label false pass;
- C006 must remain valid for the run IDs that are actually declared;
- legacy seed declarations, if present, must agree with the mutated evidence.

## 13. C002 injector

Target: `RCI-C002`, stage `pre_run`.

Mutate one explicitly declared `equal_budget_fields` path in candidate state.

Across variants/repositories use multiple surface forms, e.g.:
- `training.max_epochs`;
- `training.max_steps`;
- evaluation batch/call budget;
- sample/iteration budget where defined by that profile.

Keep split, controlled config, cache and aggregate evidence valid.

## 14. C003 injector

Target: `RCI-C003`, stage `pre_run`.

Change only candidate top-level canonical `split_hash` while:
- `require_same_split = true`;
- raw dataset identity remains unchanged;
- comparison budget/config fields remain valid.

Do not use `resolved_config.data.split_hash` as the target mechanism.

## 15. C004 injector

Target: `RCI-C004`, stage `pre_run`.

Mutate one path explicitly listed under `equal_config_fields`.

Across variants/repositories include multiple canonical paths, such as:
- batch size;
- augmentation parameter;
- model width;
- preprocessing option;
- optimizer/config parameter when that field is declared equal.

Do not mutate a path listed under `allowed_to_change`.

## 16. C005 injector

Target: `RCI-C005`, stage `pre_cache_consume`.

Mutate cached artifact source provenance relative to current RunIntent using only keys declared in `cache.invalidation_keys`.

Across variants include:
- git commit;
- config hash;
- dataset hash;
- split hash where the profile declares it;
- evaluator hash;
- environment hash where declared.

Some variants may alter more than one invalidation key, but all emitted violations must remain C005.

Do not use missing-provenance schema errors as the primary C005 benchmark target in v0.1; the main benchmark is stale-cache reuse.

## 17. C006 injector

Target: `RCI-C006`, stage `pre_aggregate`.

Canonical mutation:
- choose one declared run;
- convert its observed result to `failed`;
- preserve its real run ID, role and seed;
- clear artifact/metrics as required by the failed-result schema;
- ensure it is not included in metric aggregation;
- intentionally omit it from `reported_failed_run_ids`.

This must produce `failed_run_omission` while keeping C001 paired-seed evidence complete.

Variants may differ in which role/seed fails.

## 18. Non-target mutation validation

For every injector define the exact set of allowed changed paths.

The validator must compare canonical before/after structures and reject:
- unexpected changed fields;
- missing required target changes;
- collateral changes outside the injector's semantic footprint.

Some rules require correlated changes to preserve non-target validity.

Examples:
- C006 legitimately changes result status, metrics/artifact, and inclusion/reporting state together.
- C001 may change the set of declared/evidenced run IDs together so C006 remains internally consistent.

The mutation manifest must record all changed canonical paths.

## 19. Canonical hashing and reproducibility

Define canonical serialization:
- UTF-8;
- sorted JSON object keys;
- deterministic list ordering where order is semantically irrelevant;
- no timestamps;
- no absolute paths;
- no random UUIDs;
- no host-specific environment text.

Use SHA-256.

Generator reproducibility test:

1. generate benchmark tree in temp directory A;
2. generate again with identical version/options into B;
3. hash every generated file;
4. compare relative-path -> hash maps;
5. require exact equality.

Phase 1D acceptance requires **100% reproducibility**.

## 20. Case layout

A materialized case may use:

```
case/
  repo/
  contract.yaml
  inputs/
    pre_run.json
    pre_cache_consume.json
    pre_aggregate.json
  case_manifest.json
  ground_truth.json
  mutation_manifest.json
```

Not every case needs every stage input, but valid controls should contain all relevant stages.

The checker adapter receives only:
- repo/input state required for the lifecycle check;
- contract;
- canonical scientific inputs.

It must not receive `ground_truth.json` or mutation metadata.

## 21. Runner lifecycle

The runtime runner processes available stages in lifecycle order:

```
pre_run
  -> pre_cache_consume
  -> pre_aggregate
```

For Runtime ResearchCI:
- stop at the first blocking gate;
- record all violations returned by that gate;
- do not simulate downstream scientific admission after a block.

Also support an offline diagnostic mode that evaluates each available stage independently without changing runtime disposition. This is for debugging only and must be labeled separately from runtime metrics.

## 22. Stage-specific escape definition

For Phase 1D/1E, define an invalid experiment escape as:

> the case crosses the earliest lifecycle gate at which its frozen target violation should have been prevented.

Therefore:
- C002/C003/C004 escape if the invalid pre-run state is allowed past `pre_run`;
- C005 escapes if the invalid cache is allowed past `pre_cache_consume`;
- C001/C006 escape if invalid aggregate evidence is allowed past `pre_aggregate`.

This stage-specific definition is the operational IER definition.

## 23. Evaluation adapter interface

Implement a small adapter protocol, e.g.:

```python
class CheckerAdapter:
    name: str
    def check(stage, case_input) -> AdapterResult: ...
```

Phase 1D must include at least:

- `RuntimeResearchCIAdapter`
- `NoCheckAdapter`

The interface must be extensible for the frozen paper baselines:
- Schema Validation;
- Provenance-Only;
- Post-hoc ResearchCI.

Do not implement LLM/Agent baselines in Phase 1D.

## 24. Result schema

For every evaluated case emit a result record containing at least:

```json
{
  "case_id": "...",
  "adapter": "runtime_researchci",
  "runtime_decision": "BLOCK",
  "blocked_stage": "pre_run",
  "detected_rule_ids": ["RCI-C002"],
  "detected_locations": ["candidate.training.max_epochs"],
  "escaped": false,
  "stage_results": {},
  "elapsed_ms": 0.0
}
```

Result ordering must be deterministic.

Do not copy hidden ground truth into the adapter's raw output; joining predictions to labels happens in the evaluator after execution.

## 25. Metrics

Implement deterministic metric computation for:

- Invalid Experiment Escape Rate (IER)
- Prevention Rate
- case-level Violation Recall
- case-level Violation Precision
- False Block Rate
- exact Rule-ID Accuracy
- exact/declared Location Accuracy
- detection stage distribution
- runtime overhead
- Prevented Invalid Work Units

For Rule-ID Accuracy in v0.1:
- an invalid case is exact-correct only when the predicted rule-ID set equals the ground-truth rule-ID set.

For valid cases:
- any BLOCK counts toward False Block Rate.

## 26. Repair metrics

Do not pretend every repair operation is automatically executable.

Ground truth must label repair capability as one of:

- `auto_repairable`
- `requires_reexecution`
- `manual_resolution`

Report:
- Repair Eligibility Rate;
- Conditional Repair Success Rate on `auto_repairable` cases.

Do not score `manual_resolution_required` as a failed automatic repair.

The earlier Phase-1 target of Repair Success >= 90% applies to eligible automatic repairs; report eligibility separately.

## 27. Abstract work units

Phase 1D may use deterministic `declared_cost_units` instead of GPU-hours.

Do not call them GPU-hours.

`Prevented Invalid Work Units` is:

```
sum(cost_units of invalid cases blocked before their prohibited action)
```

Real wall-clock/GPU cost is deferred to later real-task experiments.

## 28. Dev vs locked discipline

During Phase 1D development:
- runner defaults to `dev`;
- all engineering/debug output uses `dev`;
- no tuning of ResearchCI core rules is allowed.

The locked split may be materialized and integrity-validated, but do not use locked performance to modify the engine or injectors.

After Phase 1D Planner acceptance:
- generator version/hash is frozen;
- engine commit is frozen;
- Phase 1E will run/report locked evaluation under those exact versions.

Any semantic change after locked evaluation requires an explicit version bump and a new locked run.

## 29. Benchmark integrity report

Generation must produce a machine-readable + human-readable integrity report containing:

- total case count;
- dev/locked counts;
- per-repo counts;
- per-rule counts;
- valid/invalid counts;
- injector versions;
- generator version;
- benchmark tree hash;
- duplicate case-ID check;
- opaque-ID check;
- independent postcondition pass count;
- non-target invariant pass count;
- reproducibility result.

Expected top-line values:

```
total = 240
dev = 120
locked = 120
invalid = 180
valid = 60
each rule = 30 invalid
each repo = 80
reproducibility = 100%
```

## 30. Tests

Add tests covering at minimum:

- exact cardinality/distribution;
- deterministic split assignment;
- stable opaque IDs;
- no rule name leakage in case IDs;
- all 60 valid controls pass independent structural validity;
- every invalid case has one target rule;
- every invalid case references a valid base in the same split;
- all injector target postconditions;
- all injector non-target invariants;
- generator does not call ResearchCI to produce labels;
- ground truth is not exposed through adapter input;
- two independent generations hash-identically;
- runtime runner stops at first block;
- NoCheck never blocks;
- metric formulas on hand-constructed toy predictions;
- all existing ResearchCI tests remain green.

No network calls.

## 31. Phase 1D acceptance criteria

Phase 1D is accepted when:

- the 240-case benchmark is generated exactly as frozen;
- independent integrity validation passes for all 240 cases;
- benchmark generation is bit-for-bit reproducible;
- dev/locked split is exact and deterministic;
- ground truth is independent from ResearchCI decisions;
- no hidden label/mutation metadata reaches the checker adapter;
- all prior 78 ResearchCI regressions remain green;
- benchmark tests are green;
- core C001-C006 semantics were not changed.

A preliminary **dev-only** Runtime ResearchCI report should be produced.

Do not modify benchmark labels/injectors to rescue poor ResearchCI performance.

## 32. Completion report

Executor must report:

- commit SHA;
- Python version;
- full test count/result;
- benchmark package/files added;
- case counts by split/repo/rule;
- benchmark tree hash;
- reproducibility result;
- independent integrity-validation result;
- dev-only Runtime ResearchCI metrics;
- dev-only NoCheck metrics;
- any core-engine file touched and why;
- any deviation from this plan.

Then STOP.

Do not run the locked performance evaluation as the paper result.
Do not start Phase 2 Agent experiments.

The next planned step after Planner review is **Phase 1E: frozen-baseline implementations + locked evaluation + Go/No-Go**.
