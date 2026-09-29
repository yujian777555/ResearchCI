# Phase 1B Plan — RCI-C003 Split Drift + RCI-C004 Unauthorized Config Drift

Status: **Planner-frozen for implementation**

Depends on:
- Phase 1A accepted at commit `ef8096fc36e9453d08bbd29f9e2df6c4b61def09`
- `docs/EXPERIMENT_CONTRACT_V0_1.md`
- `docs/EXPCONTRACTBENCH_V0_1.md`
- `docs/MVP_EXPERIMENT_PROTOCOL.md`

## 1. Goal

Extend the Phase 1A deterministic contract engine with two additional pre-run rules:

- `RCI-C003` — Dataset split drift
- `RCI-C004` — Unauthorized config drift

The objective is still experiment comparability, not general repository auditing.

Do not implement C005/C006 in this phase.

## 2. Contract schema amendment

Add explicit ownership instead of inferring semantics from path names.

```yaml
comparison:
  require_same_split: true

  equal_budget_fields:
    - training.max_epochs
    - training.max_steps
    - evaluation.max_batches

  equal_config_fields:
    - training.batch_size

  allowed_to_change:
    - model.optimizer
```

Rules own only their declared fields:

- C002 owns `equal_budget_fields`.
- C003 owns the canonical top-level `RunIntent.split_hash` when `require_same_split: true`.
- C004 owns `equal_config_fields`.
- `allowed_to_change` is an explicit exemption for declared comparison fields.

Do not infer rule ownership from prefixes such as `training.*`, `data.*`, or `evaluation.*`.

## 3. RCI-C003 — Dataset split drift

Lifecycle stage: `pre_run`.

### Semantics

When:

```yaml
comparison:
  require_same_split: true
```

the baseline and candidate must have identical canonical `RunIntent.split_hash`.

If hashes differ:

- decision: BLOCK
- rule ID: `RCI-C003`
- type: `split_drift`
- stage: `pre_run`
- location: `candidate.split_hash`
- expected: baseline split hash
- observed: candidate split hash

### Repair safety

Do **not** repair split drift by setting the candidate's hash label to the baseline hash.

A hash is provenance, not the data itself.

Use a non-destructive repair such as:

```json
{
  "operation": "provide_matching_split_intent",
  "path": "candidate_intent",
  "expected_split_hash": "..."
}
```

The caller must rebuild/provide an intent backed by the matching split.

If `require_same_split: false`, C003 must not block a split difference.

C003 must not inspect `resolved_config.data.*`; v0.1 uses the canonical top-level `split_hash` only.

## 4. RCI-C004 — Unauthorized config drift

Lifecycle stage: `pre_run`.

### Semantics

C004 compares only paths explicitly listed under:

```yaml
comparison:
  equal_config_fields:
    - ...
```

It must not compare the entire `resolved_config` implicitly.

This preserves the No Silent Scientific Inference rule.

For each declared path:

- if the path appears in `allowed_to_change`, skip it;
- if baseline/candidate values are equal, PASS for that field;
- if values differ, emit C004;
- if a declared path is missing, emit an explicit schema error.

A mismatch must contain:

- rule ID: `RCI-C004`
- type: `unauthorized_config_drift`
- stage: `pre_run`
- canonical location
- expected baseline value
- observed candidate value
- machine-readable repair

Because the contract explicitly declares equality for the field, a deterministic repair may restore the candidate value to the baseline value.

## 5. Ownership and de-duplication rules

The engine must not emit duplicate rule ownership for the same semantic difference.

Specifically:

- `equal_budget_fields` differences are C002, not C004;
- top-level `split_hash` differences are C003, not C004;
- C004 does not own metrics, evaluator versions, provenance hashes, or cache validity unless explicitly added in a future phase.

If a path is accidentally listed in both `equal_budget_fields` and `equal_config_fields`, the parser should reject the contradictory contract rather than producing duplicate violations.

This overlap rejection is new in Phase 1B.

An `allowed_to_change` path may appear in an equal field list; explicit permission wins and the rule skips that path.

## 6. Engine behavior

Pre-run sequence:

1. validate role identity;
2. if role identity is ambiguous/invalid, return schema errors and do not evaluate scientific comparison rules;
3. otherwise run C002 + C003 + C004;
4. return **all** violations;
5. preserve deterministic ordering.

A case with simultaneous budget and config drift must return both C002 and C004.

## 7. Required regression fixtures

### C003

At minimum:

- same split hash -> PASS;
- different split hash with `require_same_split: true` -> BLOCK;
- different split hash with `require_same_split: false` -> no C003;
- repair never mutates/relabels only the hash;
- changing `resolved_config.data.split_hash` alone does not trigger C003.

### C004

At minimum:

- equal declared config field -> PASS;
- changed `training.batch_size` -> C004;
- changed nested config path -> C004;
- changed field explicitly in `allowed_to_change` -> PASS;
- undeclared config change -> no C004;
- missing declared config path -> explicit schema error;
- C002 budget path does not also produce C004.

### Combined

At least one fixture must contain simultaneous:
- C002 budget mismatch;
- C003 split drift;
- C004 config drift.

Expected output must contain exactly those three rule IDs in deterministic order.

## 8. Required files

Expected additions/changes:

- `docs/EXPERIMENT_CONTRACT_V0_1.md` — schema amendment
- `examples/contract_v0_1.yaml`
- `src/researchci/models.py`
- `src/researchci/engine.py`
- `src/researchci/rules/split_drift.py`
- `src/researchci/rules/config_drift.py`
- `src/researchci/rules/__init__.py`
- `tests/`
- `fixtures/phase1b_cases.yaml` or equivalent deterministic fixture manifest

Equivalent names are acceptable if responsibilities remain clear.

## 9. Tests

All Phase 1A tests must remain green.

Add tests for:
- schema parsing of `require_same_split` and `equal_config_fields`;
- overlap rejection between `equal_budget_fields` and `equal_config_fields`;
- every C003/C004 fixture;
- non-destructive split repair;
- no false ownership;
- multi-rule accumulation;
- deterministic ordering;
- valid-control PASS behavior.

No network calls.

## 10. Non-goals

Do not add:

- C005 stale-cache detection;
- C006 failed-run omission;
- LLMs;
- agents;
- MLflow;
- GitHub Actions integration;
- database/server/UI;
- natural-language contract compilation;
- paper/claim auditing.

## 11. Acceptance gate

Phase 1B is accepted only if:

- all Phase 1A regressions remain green;
- all new C003/C004 fixtures pass;
- split provenance is never repaired by relabeling a hash;
- C004 inspects only explicitly declared `equal_config_fields`;
- C002/C003/C004 ownership is non-overlapping;
- simultaneous violations accumulate correctly;
- valid controls are not blocked;
- repairs remain machine-readable and deterministic.

Stop after Phase 1B and wait for Planner review before C005/C006.
