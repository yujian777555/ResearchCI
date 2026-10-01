# Phase 1E Plan — Frozen Baselines + Locked Evaluation + Go/No-Go

Status: **Planner-frozen for implementation**

Planner acceptance dependency:
- `docs/PHASE1D_R1_REVIEW.md`
- accepted Phase 1D-R1 implementation: `46725ce280a77f1b8ccb96ce476c26f75d74d57d`

## 1. Goal

Phase 1E is the first formal locked evaluation of the frozen six-rule ResearchCI v0.1 system.

Deliver exactly:

1. the remaining frozen non-Agent baselines;
2. a common evaluation matrix over the locked split;
3. machine-readable and human-readable locked reports;
4. the Phase-1 Go/No-Go decision against the frozen gate.

Phase 1E must **not**:
- change C001-C006 semantics;
- change benchmark cases, labels, profiles, injectors, split membership, or generator semantics;
- tune against locked results;
- add C007+;
- add LLM/learned components;
- start Agent Phase 2 before the locked result is finalized.

## 2. Frozen inputs

The following are immutable during Phase 1E:

- benchmark version: `0.1`
- generator version: `0.1-r1`
- benchmark tree hash:
  `sha256:5615f8bab852d7286d7150fe54c47e579ced9f943c4114e544a44e446721686f`
- benchmark cardinality: 240
- locked split: 120 = 90 invalid + 30 valid
- six frozen rule semantics: RCI-C001..RCI-C006
- accepted engine semantics: byte-identical to Phase 1C accepted rules

Before any locked evaluation, assert:
- the materialized deterministic benchmark tree still has the exact frozen hash;
- every `src/researchci/rules/**` blob matches the accepted frozen set;
- no locked report already exists unless this is an explicitly documented infrastructure-only rerun.

Any mismatch is a hard stop.

## 3. Baseline matrix

Use the frozen baseline family from `docs/MVP_EXPERIMENT_PROTOCOL.md`:

- **B0 No Check**
- **B1 Schema Validation**
- **B2 Provenance-Only**
- **B3 Post-hoc ResearchCI**
- **Ours Runtime ResearchCI**

All adapters must implement the same public benchmark adapter/result boundary.

Ground truth must be joined only by the evaluator **after** adapter execution.

No adapter may read:
- `ground_truth.json`;
- mutation manifests;
- `target_rule_id`;
- expected rule IDs/locations;
- case label.

## 4. B0 — No Check

Preserve the existing NoCheck behavior.

For every case:
- allow all lifecycle work;
- emit no rule detections;
- perform no repair;
- never block.

Do not special-case invalid cases.

## 5. B1 — Schema Validation

Implement a syntax/schema-only baseline.

It may validate:
- contract parseability;
- required fields;
- enum/type/value-shape constraints required by canonical schemas;
- construction of canonical lifecycle input objects.

It must **not**:
- call `InvariantEngine`;
- import/call `researchci.rules`;
- compare semantic equality fields from the experiment contract;
- enforce paired seeds;
- enforce budgets/config equality;
- enforce split equality;
- enforce cache freshness;
- enforce failed-run completeness.

A schema-valid but scientifically invalid case must not be blocked merely because its semantics violate C001-C006.

If all ExpContractBench v0.1 mutations are schema-valid, B1 detecting none is a valid outcome; do not manufacture schema failures to improve the baseline.

## 6. B2 — Provenance-Only

Implement a narrow deterministic artifact-lineage baseline.

Allowed scientific behavior:

### pre_run
- schema/shape checks only.

### pre_cache_consume
- compare the cached artifact's source provenance against the current run **only for keys explicitly listed in**
  `contract.cache.invalidation_keys`;
- stale declared provenance may be blocked/detected.

### pre_aggregate
- schema/shape checks only;
- do not enforce paired-seed completeness, budget/config comparability, split equality, or failed-run disclosure.

B2 must not call `InvariantEngine` or reuse C001-C006 rule functions.

The purpose is to represent a provenance/hash checker, not a weaker copy of ResearchCI.

Do not hard-code an expected number of C005 catches into the implementation.

## 7. B3 — Post-hoc ResearchCI

B3 uses the same frozen ResearchCI semantics but **only after the invalid work has already crossed its lifecycle prevention point**.

Requirements:

- evaluate all available lifecycle evidence after-the-fact;
- do not stop execution at pre-run/pre-cache/pre-aggregate;
- collect detected rule IDs and locations without using hidden benchmark truth;
- mark detection timing as `post_hoc`;
- a post-hoc detection never receives prevented-work credit;
- an invalid case detected only post-hoc still counts as an escape under the frozen IER definition;
- no automatic repair is credited as preventive runtime repair.

Do not alter C001-C006 to create a separate post-hoc rule set.

## 8. Ours — Runtime ResearchCI

Use the already accepted runtime adapter semantics:

`pre_run -> pre_cache_consume -> pre_aggregate`

- stop at the first blocking gate;
- record all violations returned by that gate;
- do not simulate prohibited downstream admission after a runtime block;
- deterministic repair evaluation remains allowed only for cases marked `auto_repairable`.

No semantic modifications are allowed during Phase 1E.

Refactoring is allowed only if behavior is proven equivalent by regression tests.

## 9. Common result schema

Every prediction must expose at least:

```json
{
  "case_id": "case_...",
  "adapter": "runtime_researchci",
  "runtime_decision": "PASS",
  "blocked_stage": null,
  "detection_stage": null,
  "detected_rule_ids": [],
  "detected_locations": [],
  "escaped": false,
  "stage_results": {},
  "elapsed_ms": 0.0,
  "repair_attempted_count": 0,
  "repair_success_count": 0
}
```

For B3, `detection_stage = "post_hoc"` when a violation is detected.

The evaluator, not the adapter, determines final correctness by joining predictions to hidden truth.

## 10. Metrics

For every adapter report:

- Invalid Experiment Escape Rate (IER)
- Prevention Rate
- Violation Recall
- Violation Precision
- False Block Rate
- exact Rule-ID Accuracy
- exact Location Accuracy
- detection-stage distribution
- mean runtime overhead
- Prevented Invalid Work Units

Also report:
- per-rule case count;
- per-rule recall;
- per-rule exact Rule-ID accuracy;
- per-repository metrics.

For automatic repair, report only when the adapter actually supports and attempts deterministic repair:

- Repair Eligibility Rate
- attempted auto-repair count
- successful auto-repair count
- Conditional Repair Success Rate

Do not assign failed repair scores to unsupported baseline adapters.

## 11. Precision / recall semantics

Preserve the R1-corrected definitions.

Precision:
- deduplicate rule IDs within each case;
- TP = detected rule IDs in that case's hidden expected set;
- FP = detected rule IDs outside it;
- detections on valid cases are FP.

Recall:
- report overall case-level detection recall;
- additionally report per-rule case-level recall.

Rule-ID accuracy:
- exact predicted rule-ID set equality.

Location accuracy:
- exact predicted expected-location set equality.

## 12. Escape and prevention semantics

Use the frozen target gate:

- C002/C003/C004 -> `pre_run`
- C005 -> `pre_cache_consume`
- C001/C006 -> `pre_aggregate`

An invalid case is prevented only if it is blocked no later than its frozen target gate.

A detection after the target gate, including all B3 post-hoc detections, is an escape.

Prevented Invalid Work Units are credited only for actual prevention before prohibited work.

## 13. Locked-run discipline

Implementation order is mandatory.

### Step A — implement baselines and evaluator using dev only

During this step:
- runner default remains `dev`;
- add/update tests;
- use only dev reports for debugging;
- do not execute `split=locked`.

### Step B — pre-lock verification

Require:
- full tests green;
- frozen benchmark tree hash exact;
- frozen rule blob set exact;
- B0/B1/B2/B3/Ours adapters pass isolation tests;
- no adapter receives hidden truth;
- dev evaluation matrix completes deterministically.

Record the evaluator code SHA before locked execution.

### Step C — one formal locked matrix run

Run all five adapters against the exact same 120 locked cases.

No code, benchmark, rule, profile, injector, or metric-definition changes are permitted between adapter runs.

Write locked outputs only after the whole matrix completes.

### Step D — freeze reports

After the locked matrix is materialized:
- do not modify results in place;
- do not rerun because a metric is disappointing;
- compute Go/No-Go directly from the frozen outputs.

## 14. Infrastructure-failure policy

A locked run may be retried only for a clear infrastructure/harness failure that prevents a complete semantic result, e.g.:
- process crash;
- truncated output;
- serialization failure;
- missing report file before metrics are exposed.

Such a retry must:
- preserve benchmark/rule semantics;
- preserve baseline semantics;
- be explicitly documented;
- use a new run ID;
- keep the failed-run artifact.

If semantic locked metrics were successfully produced and inspected, the locked split is consumed.

## 15. No tuning after locked visibility

After complete locked metrics are visible:

- no changes to C001-C006 based on those cases;
- no mutation/label/profile changes;
- no baseline semantic changes to improve comparison;
- no threshold tuning against locked results.

If a formal Go gate fails and scientific semantics must change:
- Phase 2 remains blocked;
- preserve the failed v0.1 locked result;
- version-bump the affected engine/benchmark protocol;
- create a new untouched holdout for any subsequent confirmatory evaluation.

Do not present a tuned rerun on the consumed locked split as an unbiased locked result.

## 16. Formal Phase-1 Go gate

The formal Go/No-Go decision is based on **Ours Runtime ResearchCI** on the locked split.

Require all:

- overall Violation Recall >= **0.95**
- every rule RCI-C001..C006 Recall >= **0.90**
- False Block Rate <= **0.05**
- Invalid Experiment Escape Rate <= **0.05**
- exact Rule-ID Accuracy >= **0.95**
- benchmark generation reproducibility = **1.00**
- Conditional Repair Success Rate on attempted eligible automatic repairs >= **0.90**

Also report, but do not silently substitute for the gate:
- Violation Precision;
- exact Location Accuracy;
- runtime overhead;
- Prevented Invalid Work Units.

If any required gate fails: **NO-GO**.

## 17. Baseline comparison interpretation

Do not rank baselines by recall alone.

The scientific distinction must remain explicit:

- B0 shows unguarded escape;
- B1 tests what schema correctness alone prevents;
- B2 tests what provenance/artifact lineage alone prevents;
- B3 tests post-hoc detection without runtime prevention;
- Ours tests lifecycle-aware runtime prevention.

A post-hoc system can have high detection recall while still having IER=1.0 for violations already allowed through their target gate.

## 18. Required tests

Add tests covering at minimum:

- B1 does not import/call `InvariantEngine` or rule functions;
- B1 passes semantic-only violations that remain schema-valid;
- B2 only uses declared provenance invalidation keys;
- B2 does not enforce C001/C002/C003/C004/C006 semantics;
- B3 detects with frozen ResearchCI but always counts detection as post-hoc timing;
- B3 receives zero prevented-work credit;
- RuntimeResearchCI still stops at first blocking gate;
- hidden ground truth never reaches adapters;
- evaluator joins predictions/truth only after execution;
- per-rule recall computation;
- per-repository aggregation;
- post-hoc detections count as escape;
- locked execution requires an explicit flag;
- runner still defaults to dev;
- frozen benchmark hash assertion;
- frozen rule-blob assertion;
- all previous 95 tests remain green.

No network calls.

## 19. Required outputs

Add immutable Phase 1E outputs under the benchmark report area, e.g.:

```
benchmarks/expcontractbench_v0_1/reports/
  phase1e_freeze.json
  locked_no_check.json
  locked_schema_validation.json
  locked_provenance_only.json
  locked_posthoc_researchci.json
  locked_runtime_researchci.json
  locked_comparison.json
  locked_comparison.md
  phase1e_go_no_go.json
```

Equivalent names are acceptable if unambiguous.

`phase1e_freeze.json` must contain:
- benchmark version;
- generator version;
- benchmark tree hash;
- accepted Phase 1D-R1 implementation SHA;
- evaluator code SHA;
- rule blob/tree identity;
- locked case count;
- run ID.

## 20. Completion report

Executor must report:

- implementation/evaluator commit SHA;
- Python version;
- full test count;
- confirmation frozen rule blobs unchanged;
- confirmation benchmark tree hash unchanged;
- confirmation locked split size = 120;
- B0/B1/B2/B3/Ours locked metric table;
- Ours per-rule recall table;
- Ours per-repo table;
- automatic repair attempted/success counts;
- exact locked output file names/hashes;
- formal Go/No-Go result;
- whether any infrastructure retry occurred;
- whether any locked result was observed before a code change;
- deviations from this plan.

Then STOP.

If **GO**, Planner may authorize Agent Phase 2.

If **NO-GO**, do not start Agent Phase 2.
