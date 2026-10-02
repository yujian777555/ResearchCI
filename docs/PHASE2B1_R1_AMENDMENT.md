# Phase 2B-1-R1 Amendment — Executable Model Freeze + Seed/Protocol Consistency

Status: **Planner-required repair before Phase 2B-1 acceptance**

Reviewed implementation:
`3eba271aae641824d9c07f26b197833b00c4fe32`

The implementation correctly materializes prompt/environment/runner artifacts and keeps Phase-1/core ResearchCI untouched. However the live-agent configuration is **not yet reproducibly executable** and the repository contains an internal freeze contradiction.

This amendment does not authorize a live model call or formal benchmark execution.

## 1. Resolve model identifier/version to an executable API identity

Current config:

```yaml
agent:
  provider: OpenAI
  model: GPT-5.6
  version: fixed_snapshot
```

This is not sufficient for reproducibility.

Planner verification against current OpenAI API documentation confirms an API model identifier `gpt-5.6-sol` exists, but the committed string `GPT-5.6` is not the concrete API identifier verified from the current docs, and `fixed_snapshot` is not a concrete published snapshot/model ID.

Before freeze, record either:

1. an exact immutable provider model/snapshot ID that the actual API accepts; or
2. if the provider exposes only a moving alias, record the exact alias plus the provider-returned model/version metadata at execution time and mark the study as alias-pinned rather than snapshot-pinned.

Do not invent a snapshot suffix.

No live benchmark execution is allowed in R1. A minimal capability/configuration probe is allowed only if explicitly separated from study episodes and it must not consume any benchmark scenario.

## 2. Resolve sampling-seed semantics

Current `agent_config.yaml` declares:

```yaml
sampling:
  temperature: 0
  top_p: 1
  seeds: [0, 1, 2]
```

but the repository does not establish that these values are accepted as a provider-side sampling seed by the chosen OpenAI Responses API path.

The current OpenAI Responses documentation examples expose temperature/top_p, but the Planner could not verify a seed parameter from the current documented interface.

Therefore:

- do not claim provider-level deterministic sampling unless the runner verifies the API supports it;
- if `0,1,2` are **study replicate IDs**, rename them accordingly (e.g. `replicate_ids`) and do not pass them as an unsupported model parameter;
- if provider-side seed is supported in the exact chosen endpoint/model, document the exact request field and add a dry configuration validation test.

## 3. Fix the repository freeze contradiction

Current repository state is inconsistent:

`agent_config.yaml` says:
```
seeds: [0,1,2]
```

while:

`agentbench/live_protocol/seeds.json` still says:
```json
{
  "status": "frozen_placeholder",
  "seeds": []
}
```

and the historical `phase2b_freeze.json` still reports:
- `PLACEHOLDER_VALUES_REMAIN`
- `seed_list_empty_placeholder: true`

The historical Phase 2B-0 record may remain immutable, but Phase 2B-1 must produce a new authoritative freeze record with no contradiction.

Required:
- update `seeds.json` to the final semantics (provider seed or replicate IDs);
- include its new hash in the Phase 2B-1 freeze;
- compute a new Phase 2B-1 composite protocol hash over the exact finalized:
  - agent config
  - evaluation protocol
  - seed/replicate configuration
  - system prompt
  - environment identity
  - scenario hash
  - tool-schema hash
  - live-runner source hash.

## 4. Freeze API/runner contract before live study

The live-runner skeleton is acceptable as infrastructure, but before acceptance add a machine-readable provider contract describing the exact intended request surface.

At minimum record:
- API family/endpoint (e.g. Responses API);
- exact model identifier field;
- supported sampling fields actually used;
- max-output/token parameter mapping;
- tool-call interface mapping;
- how usage/token counts are captured;
- how provider-returned model metadata is recorded.

No API key/secret may be committed.

## 5. System-prompt note

The current prompt is accepted as a shared integrity-aware research instruction for all A0-A4 conditions, but Phase 2B analysis must explicitly report it as common context across conditions.

Do not vary this prompt by condition.

## 6. Required R1 tests

Add tests proving:
- no `TBD`, `fixed_snapshot`, or placeholder model-version marker remains in the authoritative live configuration;
- `seeds.json` and `agent_config.yaml` cannot disagree on seed/replicate semantics;
- the Phase 2B-1 composite protocol hash changes if any frozen component changes;
- provider request config contains only documented/validated request fields;
- condition/family/hidden metadata leakage remains absent;
- no live benchmark episode is executed;
- all previous regressions remain green.

## 7. Completion report

Report:
- new commit SHA;
- exact provider API/endpoint;
- exact model ID/version semantics;
- provider-side sampling seed support: YES/NO;
- final replicate/seed semantics;
- new seeds/replicate-config hash;
- new composite Phase 2B-1 protocol hash;
- provider-contract hash;
- prompt/environment/runner hashes;
- tests;
- live benchmark episodes executed: 0;
- any non-benchmark capability probe performed;
- scope audit;
- deviations.

Then STOP.

Phase 2B live evaluation remains blocked until Planner accepts this R1.
