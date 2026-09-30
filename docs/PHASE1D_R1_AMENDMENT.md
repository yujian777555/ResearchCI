# Phase 1D-R1 Amendment — Benchmark Integrity, Metric Correctness, and Diversity

Status: **Planner-required repair before Phase 1D acceptance**

Reviewed implementation:
`98acb2107735affd1b7b3e8270f6b031bb76403e`

This amendment does **not** change C001-C006 semantics. The ResearchCI rule engine remains frozen.

## 1. Why R1 is required

The current Phase 1D implementation produces the requested 240 files/cases and the dev RuntimeResearchCI run is promising, but several benchmark-integrity claims are not yet independently established.

Three classes of defects must be fixed before the locked split can be frozen:

1. integrity validation currently overstates what it validates;
2. several benchmark metrics are not implemented according to the frozen definitions;
3. the nominal repository/control diversity is largely duplicated.

The locked split must not be evaluated until these are repaired.

## 2. Independent non-target validation must be real

Current validator behavior increments:

```python
non_target_pass += int(target_ok)
```

This is not a non-target invariant check.

For each injector, implement an independent structural validator that checks both:

- the target postcondition is true; and
- all non-target scientific invariants remain valid.

The validator must not call ResearchCI.

At minimum independently check the relevant frozen semantics:

- C001 cases: seed comparability is violated while C006 run accounting is internally valid;
- C002 cases: only a declared budget equality is violated; split/config/cache/aggregate remain valid;
- C003 cases: only canonical top-level split equality is violated;
- C004 cases: only an explicitly equal config field is violated;
- C005 cases: only declared cache provenance equality is stale;
- C006 cases: failed-run disclosure is violated while paired-seed evidence remains complete.

`non_target_invariant_pass_count` may only increment after those checks actually pass.

## 3. Valid controls require independent semantic validation

Current valid-control validation only checks that lifecycle input files exist.

Replace this with independent structural validity checks covering all six rule dimensions, without invoking ResearchCI.

A valid control must independently satisfy:
- paired seed evidence completeness;
- budget equality;
- split equality when required;
- declared config equality;
- cache provenance equality for all invalidation keys;
- complete run accounting / explicit failure handling.

The integrity report's `valid_control_structural_pass_count` must represent these checks, not file existence.

## 4. Mutation manifests must be complete

The mutation manifest must list the complete canonical before/after diff.

Current examples are incomplete:
- C001 changes run IDs, RunIntent evidence, observed results, included IDs, and legacy seed declarations, but does not list all changed paths;
- C006 changes status, artifact hash, metrics, included IDs, and failure-reporting state, but does not list all changed paths.

Preferred implementation:

1. compute a canonical recursive diff between base and mutated scientific inputs;
2. derive `changed_paths` from that diff;
3. compare it against the injector's allowed semantic footprint;
4. fail generation/validation on any unexpected path.

Do not rely on manually incomplete path lists.

## 5. Reproducibility must be measured, not declared

`generation_metadata.json` currently writes `"reproducible": true` unconditionally.

The existing unit test that generates twice is useful, but the benchmark integrity report itself must be backed by an actual reproducibility comparison.

Implement a reproducibility verifier that:
- generates the benchmark twice in separate temporary roots;
- compares relative-path SHA-256 maps for deterministic generated content;
- records compared file count, mismatch count, and pass/fail.

The committed integrity report must derive `reproducible` from that check rather than a constant.

Avoid recursive inclusion of integrity/report files in the compared benchmark hash.

## 6. Fix metric definitions before locked evaluation

### 6.1 Violation Precision

Current implementation counts:

```python
bool(detected & target) / total_invalid
```

This does not penalize extra wrong rule IDs and ignores detections on valid cases.

For v0.1, compute rule-detection precision over deduplicated per-case rule detections:

```
TP = detected rule IDs that are in that case's ground-truth set
FP = detected rule IDs not in that case's ground-truth set
precision = TP / (TP + FP)
```

Detections on valid cases are false positives.

Keep case-level recall separately if desired, but name it clearly.

### 6.2 Location Accuracy

The frozen benchmark is single-target and has declared expected locations.

Use exact expected-location-set equality for the reported exact location accuracy.

Do not count a strict subset as exact-correct.

If a relaxed containment metric is useful, report it under a different name.

### 6.3 Conditional Repair Success

Current implementation treats "a rule was detected" as successful repair.

That is not repair success.

For `auto_repairable` cases:
1. extract the machine repair from the blocking violation;
2. apply it to a deep copy of the case input;
3. rerun the relevant lifecycle checker;
4. require the original target violation to disappear;
5. require no new violation to appear.

Report:
- repair eligibility rate;
- attempted auto-repair count;
- successful auto-repair count;
- conditional repair success rate.

Cases marked `requires_reexecution` or `manual_resolution` are not automatic-repair failures.

## 7. Prevent metric-regression tests

Add hand-constructed tests proving:
- one correct + one extra wrong rule ID lowers precision;
- a false detection on a valid case lowers precision;
- detecting only one of two expected locations does not get exact location credit;
- merely detecting an auto-repairable violation does not count as repair success unless the repair is applied and revalidation passes.

## 8. Benchmark diversity must be substantive

The current three profiles share the same contract structure, values, config paths, and provenance; they differ primarily by `repo_id` and task name.

Also, `Profile.base_case(valid_index)` currently does not use `valid_index` to change the scientific input state, so the 20 valid controls per profile are effectively repeated controls.

Before freezing the locked split:

### 8.1 Distinct controls

Use `valid_index` to generate deterministic but valid variation in scientific state, e.g.:
- equal baseline/candidate budgets;
- equal controlled config values;
- split/data/evaluator/environment fingerprints;
- allowed-change values where scientifically permitted.

Require **20 distinct input-tree hashes per repository profile** for the 20 valid controls.

All controls must remain independently valid.

### 8.2 Distinct profile schemas

Make the three controlled profiles structurally distinct enough that they are not aliases.

For example, use profile-specific subsets/names of:
- budget fields;
- equal config fields;
- allowed changes;
- cache invalidation keys;
- resolved-config structure.

The core rule engine is generic and must not be changed to special-case profile names.

The goal is not real-repository generalization yet; it is to avoid triplicating one synthetic schema under three labels.

## 9. Dev report status

The current dev run:
- IER 0.0;
- Prevention 1.0;
- Rule-ID accuracy 1.0;
- FBR 0.0

is useful preliminary evidence that the runtime engine matches the generated cases.

However, do not treat the current integrity claims, precision, location accuracy, or repair-success figures as frozen paper evidence until R1 is complete.

After R1, regenerate the entire benchmark. The benchmark tree hash is expected to change.

## 10. Required R1 completion evidence

Report:
- new commit SHA;
- full test count;
- new benchmark tree hash;
- exact 240-case distribution;
- 20 unique valid-control input hashes per repo;
- actual two-generation reproducibility comparison;
- independent target-postcondition count;
- independent non-target-invariant count;
- independent valid-control semantic count;
- complete-diff validation count;
- corrected dev RuntimeResearchCI metrics;
- corrected dev NoCheck metrics;
- auto-repair attempted/success counts;
- confirmation that no `src/researchci/rules/**` file changed.

Then STOP.

Do not evaluate locked performance and do not begin Phase 1E until Planner acceptance.
