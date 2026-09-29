# Phase 1C Plan — RCI-C005 Stale Cache Reuse + RCI-C006 Failed-Run Omission

Status: **Planner-frozen for implementation**

Depends on:
- Phase 1A accepted
- Phase 1B accepted at commit `462abc1e20ab61bc68daa992e192c6b3f91bc5a8`
- `docs/EXPERIMENT_CONTRACT_V0_1.md`
- `docs/EXPCONTRACTBENCH_V0_1.md`
- `docs/MVP_EXPERIMENT_PROTOCOL.md`

## 1. Goal

Complete the six-rule v0.1 invariant engine with:

- `RCI-C005` — Stale cache reuse
- `RCI-C006` — Failed-run omission / aggregate run accounting

This phase completes rule implementation only.

Do **not** build the full 240-case ExpContractBench generator yet.
Do **not** start Agent stress testing.

## 2. Existing contract fields now become executable

The v0.1 example already declares:

```yaml
completeness:
  failed_runs:
    must_be_explicit: true

cache:
  invalidation_keys:
    - git_commit
    - config_hash
    - dataset_hash
    - evaluator_hash
```

Phase 1C must parse these fields into the canonical contract model.

Suggested canonical fields:

```python
failed_runs_must_be_explicit: bool
cache_invalidation_keys: tuple[str, ...]
```

No silent defaults for a malformed value.

Backward compatibility:
- if `completeness.failed_runs.must_be_explicit` is absent, default to `False`;
- if `cache.invalidation_keys` is absent, default to an empty tuple;
- if present, types and keys must be validated.

## 3. Supported cache provenance keys

For v0.1, `cache.invalidation_keys` may reference only these canonical top-level `RunIntent` provenance fields:

- `git_commit`
- `config_hash`
- `dataset_hash`
- `split_hash`
- `evaluator_hash`
- `environment_hash`

Reject unknown keys at contract-parse time.

Do not infer invalidation dependencies from file names, config prefixes, or repository state.

## 4. New canonical cache models

Add a small typed cache-consumption model.

Suggested shape:

```python
@dataclass
class CachedArtifactManifest:
    artifact_id: str
    artifact_hash: str
    source_provenance: dict[str, str]

@dataclass
class CacheConsumeIntent:
    current_run: RunIntent
    cached_artifact: CachedArtifactManifest
```

Equivalent naming is acceptable.

The artifact manifest must describe the provenance that actually produced the cached artifact.

Do not mutate provenance values during validation.

## 5. RCI-C005 — Stale cache reuse

Lifecycle stage:

`pre_cache_consume`

### Semantics

For every key explicitly listed in:

```yaml
cache:
  invalidation_keys:
    - ...
```

compare:

```
current RunIntent canonical provenance
vs
cached artifact source provenance
```

If all declared keys match: PASS for C005.

If any declared key differs: BLOCK.

Return **all** stale-key mismatches.

Each stale mismatch must include:

- rule ID: `RCI-C005`
- type: `stale_cache_reuse`
- stage: `pre_cache_consume`
- location: `cached_artifact.source_provenance.<key>`
- expected: current-run provenance value
- observed: cached-artifact provenance value
- machine-readable repair

### Repair safety

Never repair stale cache by rewriting the provenance label.

Required repair semantics should be non-destructive, e.g.:

```json
{
  "operation": "invalidate_and_recompute",
  "artifact_id": "cache-123",
  "mismatched_key": "config_hash"
}
```

The cache must be invalidated/recomputed from current inputs.

### Missing provenance

If a declared invalidation key is missing from the cached artifact manifest:
- BLOCK;
- explicit C005 schema error;
- do not assume equality.

If a provenance field changes but that key is **not** listed in `cache.invalidation_keys`, C005 must not block because of that field.

## 6. RunResult semantics required for C006

C006 needs real failed runs.

Tighten `RunResult.status` for v0.1 to:

- `success`
- `failed`

A successful result must have a non-empty `artifact_hash`.

A failed result may use `artifact_hash: null` and may have empty metrics.

Do not fabricate an artifact for failed runs merely to satisfy the schema.

Optional failure metadata may be added if lightweight, but is not required for Phase 1C.

## 7. AggregateIntent accounting fields

Extend `AggregateIntent` with explicit aggregation accounting.

Suggested fields:

```python
included_run_ids: tuple[str, ...] = ()
reported_failed_run_ids: tuple[str, ...] = ()
```

Semantics:

- `baseline_run_ids + candidate_run_ids` = declared runs for the comparison.
- `included_run_ids` = successful runs actually consumed by the metric aggregation.
- `reported_failed_run_ids` = failed runs explicitly disclosed by the aggregate/evidence record.
- `observed_results` = actual RunResult records known at aggregation time.

Run IDs must be unique where uniqueness is scientifically required.

## 8. RCI-C006 — Failed-run omission / run accounting

Lifecycle stage:

`pre_aggregate`

C006 is active when:

```yaml
completeness:
  failed_runs:
    must_be_explicit: true
```

### Required accounting invariant

Every declared run must be accounted for as exactly one of:

1. a successful observed result included in `included_run_ids`; or
2. a failed observed result listed in `reported_failed_run_ids`.

Conceptually:

```
declared runs
=
included successful runs
UNION
explicitly reported failed runs
```

with no silent disappearance and no invalid overlap.

### Required checks

At minimum detect:

1. declared run has no `RunResult`;
2. failed observed run is missing from `reported_failed_run_ids`;
3. failed run appears in `included_run_ids`;
4. successful declared run is silently omitted from `included_run_ids`;
5. a success is falsely listed in `reported_failed_run_ids`;
6. unknown/undeclared run ID appears in included or reported-failed accounting;
7. duplicate/conflicting RunResult records for the same run ID.

The benchmark's canonical C006 violation is case (2): a known failed run silently omitted from reporting.

Other accounting defects may use `schema_error` / `run_accounting_error` under rule ID C006.

### Failed-run omission output

For the canonical omission case:

- rule ID: `RCI-C006`
- type: `failed_run_omission`
- stage: `pre_aggregate`
- location: `reported_failed_run_ids`
- observed: omitted failed run ID(s)
- expected: explicit disclosure

Repair may safely propose adding the already-observed failed run ID to `reported_failed_run_ids`.

It must never:
- change a failed status to success;
- fabricate metrics;
- fabricate an artifact.

## 9. Relationship to C001

C001 and C006 have separate ownership:

- C001: paired seed-set comparability.
- C006: declared run/result accounting and explicit failure disclosure.

At `pre_aggregate`, run **both** and accumulate all violations.

Do not make C006 silently replace C001.

If a case has both a missing paired seed and an omitted failed run, both relevant rule IDs should be returned when the available evidence supports both.

## 10. Engine lifecycle

After Phase 1C the engine has:

```
pre_run:
  role guard
  C002
  C003
  C004

pre_cache_consume:
  C005

pre_aggregate:
  C001
  C006
```

Add a simple typed/function entry point for `pre_cache_consume`.

All stages remain deterministic and side-effect free.

## 11. Required C005 fixtures

At minimum:

- all declared invalidation keys match -> PASS;
- stale `git_commit` -> C005 BLOCK;
- stale `config_hash` -> C005 BLOCK;
- stale `dataset_hash` -> C005 BLOCK;
- stale `evaluator_hash` -> C005 BLOCK;
- multiple stale keys -> all C005 violations returned deterministically;
- changed but undeclared provenance key -> no C005;
- missing declared cached provenance key -> explicit C005 schema error;
- repair is `invalidate_and_recompute`, never provenance relabeling.

## 12. Required C006 fixtures

At minimum:

- all declared runs succeed and are included -> PASS;
- one failed run explicitly reported -> PASS;
- known failed run omitted from `reported_failed_run_ids` -> C006 `failed_run_omission`;
- failed run incorrectly included in metric set -> BLOCK;
- successful run silently omitted -> BLOCK;
- declared run with no result -> BLOCK;
- success falsely reported as failed -> BLOCK;
- unknown accounting run ID -> BLOCK;
- duplicate/conflicting result ID -> BLOCK.

## 13. Combined regression

Create at least one pre-aggregate case where C001 and C006 both fire.

The result must contain both rule IDs with deterministic ordering.

Also preserve the Phase 1B combined pre-run regression for C002+C003+C004.

## 14. Contract/parser safety tests

Add tests proving:

- unknown cache invalidation key is rejected;
- invalid `must_be_explicit` type is rejected;
- empty invalidation-key list is allowed and disables C005 checks;
- missing Phase 1C contract fields preserve backward-compatible inactive behavior;
- duplicate invalidation keys are rejected;
- declared run IDs and result IDs cannot become ambiguous without a blocking schema/accounting error.

## 15. Required files

Expected additions/changes include:

- `docs/EXPERIMENT_CONTRACT_V0_1.md`
- `examples/contract_v0_1.yaml` if clarification is required
- `src/researchci/models.py`
- `src/researchci/engine.py`
- `src/researchci/rules/cache.py` or equivalent
- `src/researchci/rules/failed_runs.py` or equivalent
- `src/researchci/rules/__init__.py`
- `tests/test_phase1c.py`
- `fixtures/phase1c_cases.yaml` or equivalent

## 16. Non-goals

Do not add:

- the full 240-case benchmark generator;
- real sklearn/PyTorch/text repositories;
- Agent stress testing;
- LLM calls;
- MLflow;
- GitHub Actions integration;
- database/server/UI;
- pre-claim natural-language checking;
- new rule IDs beyond C005/C006.

## 17. Acceptance gate

Phase 1C is accepted only if:

- all prior Phase 1A/1B tests remain green;
- C005 checks only explicitly declared invalidation keys;
- stale-cache repair never relabels provenance;
- C006 makes every declared run explicitly accountable;
- known failed runs cannot silently disappear;
- C001+C006 accumulation is deterministic;
- all six rule IDs now have their intended lifecycle ownership;
- valid controls do not false-block;
- no C007+ scope expansion occurs.

After completion, STOP and wait for Planner review.

The next planned stage, if Phase 1C passes, is **Phase 1D: deterministic ExpContractBench v0.1 generation + evaluation harness**, not Agent stress testing.
