# Phase 2B-STATS-0-R1 Amendment — Cluster-Multiplicity-Safe Bootstrap + Endpoint Eligibility

Status: **Planner-required final offline repair before STATS-0 acceptance**

Reviewed implementation commit:
`4d0d74b509de5c4c1bc621e822dcbc91b5e80bc4`

The statistical direction is correct: Wilcoxon is removed, A4-vs-A3 is primary, A4-vs-A0 is prespecified end-to-end, the 10-point VTCR non-inferiority margin is frozen, the pilot/formal replicate sets are disjoint, and the condition-order rule is deterministic. Three implementation/freeze defects remain.

## 1. Scenario-cluster bootstrap currently loses repeated-cluster multiplicity for paired endpoints

Current `scenario_cluster_bootstrap()` resamples scenario IDs with replacement and flattens copied records. However `vtcr_noninferiority()` reconstructs pairs with the key:

```
(scenario_id, replicate_id)
```

When the same scenario is sampled twice in one bootstrap draw, the duplicated records have identical keys and are collapsed by the dictionary. Therefore a scenario selected twice receives weight one rather than weight two.

This invalidates the intended cluster-bootstrap distribution for VTCR and any paired-binary endpoint implemented the same way.

### Required repair

Preserve every sampled cluster occurrence as a distinct bootstrap instance.

Acceptable implementations include:
- adding an internal per-draw `__bootstrap_cluster_instance` identifier to copied records and including it in pairing keys; or
- passing a multiset/weighted cluster representation to the statistic; or
- another deterministic design that provably preserves with-replacement multiplicity.

The internal bootstrap instance identifier must never become part of the persisted scientific dataset or live-agent input.

### Required tests

Construct a deterministic bootstrap/sample in which one scenario appears multiple times and prove:
- the repeated cluster contributes repeated weight to the statistic;
- all replicate blocks and compared conditions inside each selected scenario occurrence remain paired;
- no individual action/episode sampling occurs.

The existing “cluster record count is even” test is insufficient because it does not detect duplicate-cluster collapse.

## 2. Endpoint-specific paired-binary analysis and efficacy eligibility are not yet enforced

The frozen protocol requires EIFR and VTCR to use:
- paired absolute risk difference;
- scenario-cluster bootstrap;
- exact paired McNemar support;
- exclusion of `INFRA_INVALID` episodes from efficacy denominators.

Current code has a point-estimate/McNemar helper and a VTCR bootstrap helper, but:
- there is no authoritative EIFR scenario-cluster analysis path;
- `vtcr_noninferiority()` does not exclude infrastructure-invalid episodes;
- `cier_summary()` / `cier_cluster_bootstrap()` do not exclude infrastructure-invalid episodes.

This means the code can silently include an authentication/network-invalid episode in efficacy rates even though the protocol says it is excluded.

### Required repair

Add one authoritative efficacy-eligibility rule used by all three endpoints.

At minimum:
- `INFRA_INVALID` episodes are excluded from EIFR, VTCR, CIER and attempt-rate efficacy denominators;
- agent-caused incomplete trajectories (F5 / step exhaustion / agent timeout/tool misuse) remain outcomes and are **not** excluded merely because they are incomplete;
- endpoint analyzers report excluded infrastructure-invalid counts.

Implement an endpoint-specific paired-binary analysis function for EIFR and reuse the same pairing/bootstrap machinery for VTCR where practical.

For EIFR A4-vs-A3 and A4-vs-A0 it must return:
- condition rates;
- paired absolute risk difference;
- 95% scenario-cluster bootstrap percentile interval;
- discordant counts;
- exact paired McNemar p-value;
- number of eligible matched pairs;
- infrastructure-invalid exclusions.

For VTCR it must preserve the frozen one-sided 97.5% lower bound and -0.10 margin, using the multiplicity-safe scenario bootstrap.

For CIER:
- exclude infrastructure-invalid episodes before pooled numerator/denominator and attempt-rate computation;
- retain the zero-denominator / <95% estimability rule;
- report infra-invalid exclusions.

### Missing-pair rule

If an infrastructure-invalid episode removes one condition member from a matched pair, do not silently compare that condition to a non-matched episode.

For a paired A-vs-B analysis, only blocks with eligible outcomes for both A and B enter that paired comparison. Report how many blocks were dropped because one/both paired members were infrastructure-invalid.

## 3. STATS-0 freeze points to the wrong DeepSeek protocol lineage

The accepted DeepSeek provider protocol is DS-0-R1:

`sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`

Current STATS-0 freeze/scope artifacts instead record the obsolete DS-0 parent:

`sha256:1a74ed0bb50f615f46f1d1d83e001821a16b64d4df0e16edb8a35bcaf2d35544`

No provider code was modified by STATS-0, so this is a freeze-lineage/documentation defect, not a provider implementation regression.

### Required repair

R1 reports must identify:
- active DeepSeek live protocol = `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`;
- historical DS-0 parent, if retained, = `sha256:1a74ed0bb50f615f46f1d1d83e001821a16b64d4df0e16edb8a35bcaf2d35544`;
- historical OpenAI protocol unchanged = `sha256:8c21a5a702bdb3b494457fe54c47261df9fdc6e4629149ad84353717219a030c`.

Do not alter the accepted DS-0-R1 provider files to fix this report reference.

## 4. Preserve accepted STATS-0 decisions

Do not change:
- matched block = scenario_id × replicate_id;
- A4 vs A3 primary prevention comparison;
- A4 vs A0 end-to-end comparison;
- A1/A2 descriptive/mechanistic role;
- 10,000 scenario-cluster bootstrap draws;
- bootstrap seed 20261004;
- percentile intervals;
- VTCR non-inferiority margin -0.10;
- strict decision lower bound > -0.10;
- CIER <95% estimability gate;
- five-row cyclic Latin-square order rule;
- pilot P0-P2 / 270 episodes;
- formal F0-F9 / 900 fresh episodes;
- pilot/formal separation;
- INFRA_INVALID replacement limit = 1;
- unresolved INFRA_INVALID stop threshold >5%;
- F1-F7 taxonomy;
- no active Wilcoxon path.

## 5. R1 tests

Add deterministic tests proving:
1. duplicate scenario selections retain bootstrap multiplicity;
2. pair structure survives duplicate-cluster resampling;
3. EIFR scenario-cluster analysis returns risk difference, CI, discordant counts and exact McNemar;
4. VTCR bootstrap uses duplicate cluster weight correctly;
5. infrastructure-invalid members are excluded from paired efficacy comparison;
6. a pair with one infra-invalid member is dropped from that A-vs-B paired comparison and counted;
7. agent-caused incomplete trajectory remains in the efficacy dataset;
8. CIER/attempt-rate excludes infra-invalid episodes but retains agent-caused incomplete outcomes;
9. low CIER estimability behavior remains unchanged;
10. active DeepSeek protocol hash in R1 freeze is the accepted DS-0-R1 hash;
11. no active Wilcoxon path;
12. no network/API/live/benchmark execution.

## 6. Freeze/reporting

Do not overwrite the original STATS-0 artifacts. Add R1-specific freeze/regression/scope/manifest-or-analysis audit reports and a new STATS-0-R1 statistical protocol hash.

Parent STATS-0 protocol:
`sha256:d523276ca0ac1f7e4f426e5f37eebe732de62c80a768b0cab59bb05e30fd53bf`

The new composite must cover the corrected analysis source and R1 freeze artifacts as appropriate.

## 7. Scope / stop

No changes to:
- C001-C006;
- Phase 1 artifacts;
- Phase 2A scenario/workspace semantics;
- DeepSeek DS-0-R1 provider implementation/protocol;
- historical OpenAI protocol;
- system prompt;
- tool schema;
- historical live canary evidence.

Strictly offline:
- DeepSeek API calls = 0
- OpenAI API calls = 0
- runtime network calls = 0
- live episodes = 0
- benchmark episodes = 0

Run full regression and STOP.

Phase 2B-DS-1 remains blocked until Planner accepts STATS-0-R1.
