# Phase 1D-R1 Planner Review — ACCEPTED / Benchmark Frozen for Locked Evaluation

Planner: ChatGPT  
Reviewed implementation: `46725ce280a77f1b8ccb96ce476c26f75d74d57d`  
Benchmark: ExpContractBench v0.1  
Generator version: `0.1-r1`

## Verdict

**ACCEPTED**

Phase 1D-R1 closes the integrity, metric-correctness, and diversity defects identified in `docs/PHASE1D_R1_AMENDMENT.md`.

The benchmark and the six-rule runtime engine are now frozen for Phase 1E locked evaluation.

## Acceptance evidence

### Exact benchmark shape

- total cases: **240**
- invalid: **180**
- valid: **60**
- dev / locked: **120 / 120**
- each repository profile: **80**
- each frozen rule RCI-C001..C006: **30 invalid cases**

### Independent benchmark integrity

- independent target postconditions: **180 / 180**
- independent non-target invariants: **180 / 180**
- independent valid-control semantic validation: **60 / 60**
- complete canonical mutation diff validation: **180 / 180**
- duplicate case IDs: **0**
- opaque case IDs: **PASS**

The validator no longer derives non-target success from target success. `validate_mutation()` checks the target dimension independently, requires all non-target scientific dimensions to remain valid, and never calls ResearchCI as its benchmark oracle.

Valid controls are independently checked across all six frozen scientific dimensions rather than only checking file presence.

### Diversity closure

The three controlled profiles now have distinct contract/config surfaces.

Each repository has **20 distinct valid-control input-tree hashes**:

- `tabular_sklearn`: 20
- `vision_pytorch`: 20
- `text_classification`: 20

The valid controls vary scientific input state deterministically while remaining independently valid.

### Reproducibility

Two independent generations plus comparison to the committed materialized reference were performed.

- deterministic files compared: **1690**
- generation A/B mismatches: **0**
- reference mismatches: **0**
- reproducibility: **100%**
- benchmark tree hash:

`sha256:5615f8bab852d7286d7150fe54c47e579ced9f943c4114e544a44e446721686f`

### Metric corrections

The R1 implementation now uses:

- deduplicated rule-ID TP/FP precision;
- false rule detections on valid cases as precision false positives;
- exact expected-location-set equality for location accuracy;
- actual repair application followed by revalidation;
- no automatic-repair penalty for `requires_reexecution` / `manual_resolution` cases;
- stage-aware escape/prevention semantics.

The regression suite explicitly covers the previously incorrect metric cases.

### Dev-only evidence

Runtime ResearchCI on the development split:

- IER: **0.0**
- Prevention Rate: **1.0**
- Violation Precision / Recall: **1.0 / 1.0**
- Rule-ID Accuracy: **1.0**
- Location Accuracy: **1.0**
- False Block Rate: **0.0**
- auto-repair attempted / successful: **45 / 45**
- Conditional Repair Success: **1.0**
- Prevented Invalid Work Units: **9000**

NoCheck on the development split:

- IER: **1.0**
- Prevention Rate: **0.0**
- False Block Rate: **0.0**

These remain development evidence only and are not the locked paper result.

### Frozen rule-engine verification

The full `src/researchci/rules/**` blob set at the accepted Phase 1C point
`316d4897aa07c5eedf27709ca049e6e14b1b2316`
is byte-identical to the rule blob set at
`46725ce280a77f1b8ccb96ce476c26f75d74d57d`.

Therefore Phase 1D/R1 did **not** tune C001-C006 semantics to the benchmark.

### Tests

- full suite: **95 passed / 0 failed**

## Freeze record for Phase 1E

The following are frozen inputs to the first locked evaluation:

- repository implementation snapshot: `46725ce280a77f1b8ccb96ce476c26f75d74d57d`
- C001-C006 scientific semantics: unchanged from accepted Phase 1C
- benchmark version: `0.1`
- generator version: `0.1-r1`
- benchmark tree hash: `sha256:5615f8bab852d7286d7150fe54c47e579ced9f943c4114e544a44e446721686f`
- locked split: 120 cases = 90 invalid + 30 valid

From this point until the locked evaluation is recorded:

- do not modify `src/researchci/rules/**`;
- do not modify existing benchmark cases, labels, injectors, profiles, or split membership;
- do not use locked performance to tune ResearchCI;
- do not begin Agent Phase 2.

Any semantic rule or benchmark change after the locked run requires an explicit version bump and a new locked evaluation.

## Next step

Proceed to **Phase 1E: Frozen Baselines + Locked Evaluation + Go/No-Go**.
