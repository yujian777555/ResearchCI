# Phase 2B-DS-1-R2 Amendment — Close the Offline Qualification Gaps

**Status: PLANNER REQUIRED / STRICTLY OFFLINE**
Reviewed R1 implementation: `6ce87b31c6ca31f47fceb71dd969d136b5d007ed`.
Parent R1 planner spec: `docs/PHASE2B_DS1_R1_AMENDMENT.md`.
Issue: #15.

**Decision:** R1 is **not accepted**. The narrow fix to remove `sleep=lambda _:None` and add typed result fields is valid, but the promised durable, instrumented, single-entrance preflight/canary qualification path is not yet implemented. Do not run `GET /models`, `POST /responses`, or a canary.

## Verified blockers

### B1. There is still no operational, durable preflight transport audit

`agentbench/deepseek_live_canary/preflight.py` declares `http_attempts_observed` and `http_attempt_count_verified`, but `run_preflight()` does not instrument HTTP transport; it always leaves those fields at `None` / `False`. There is no verified `max_retries=0` SDK client construction.

`run_preflight()` writes its first audit event **only after** `models.list()` has completed/failed; no durable `preflight_start` or transport-attempt event is emitted before network. A crash before return would again erase the only provider outcome evidence. The `provider_outcome_persisted` field is never transitioned to true as part of a validated, durable successful result.

`PreflightAuditLog.append()` writes arbitrary event dicts without applying the existing redaction helper: event values could inadvertently persist secrets.

**R2 required:**
- Introduce one typed/audited offline-exercisable preflight coordinator or equivalent function connecting controlled client construction, HTTP-attempt instrumentation, primary append-only sanitized event log, verified result persistence, and canary eligibility.
- Use injectable `httpx.MockTransport` (or an equivalent fully offline fake) in tests to prove **SDK invocation count != assumed HTTP wire attempts** and prove implicit SDK `max_retries=0`. Do not infer verified transport count merely from invoking `client.models.list()`.
- Append+fsync a sanitized `preflight_start` and each observed transport attempt/result/error before any derived summary. Persist a sanitized preflight outcome event *before* writing derived summaries; a simulated summary serialization crash must preserve the provider outcome that was actually observed.
- Encode `UNKNOWN` rather than `False` when model presence or transport count is unobserved.
- Redact/allowlist log values and ensure no arbitrary secret-bearing dict can be persisted. Do not save full headers/catalog/request bodies.
- Make `provider_outcome_persisted` true only after a real successful durable primary evidence event, and require verified `http_attempt_count_verified`, exactly one observed model-list HTTP attempt, target presence, and persisted PASS before eligibility for any future live canary.
- Failure to observe a transport attempt/commit an event must fail closed rather than re-issue the request.

### B2. The checked-in CLI does not exercise the offline path

`cli.py` returns `0` for `offline-selftest` unconditionally; this checks nothing. `preflight`/`canary` correctly reject R1 live runs, but the canonical entrypoint has no tested state machine sequencing or persisted PASS guard.

**R2 required:**
- The checked-in `offline-selftest` command must invoke an actual deterministic fake end-to-end preflight and canary qualification flow (with zero network and no credential reads); nonzero exit on failure.
- Keep `preflight`/`canary` modes **disabled** in R2 until a separate Planner live authorization. Their future transition must be one authoritative checked-in function, rather than ad-hoc script.
- A synthetic canary MUST NOT run if preflight is failed, unknown, unverifiable, missing its durable PASS evidence, or already consumed. Prove one-preflight/one-canary gating in offline tests.

### B3. Frozen canary qualification still cannot be evaluated correctly

`canary.py` still extracts final text using `str(item.get("content", ...))`. For actual Responses `message.content=[{"type":"output_text","text":"..."}]`, this is the Python representation of a list, **not canonical extracted assistant text**. The code currently returns `marker_present` without a comprehensive PASS/FAIL gate; it can therefore overlook zero/extra/wrong tool calls or invalid replay.

`TASK` omits the backticks from the exact text frozen in `docs/PHASE2B_DS1_PLAN.md`. Historical old-harness evidence must not be edited; this new version must explicitly declare the corrected task hash.

**R2 required:**
- Implement typed extraction of supported `output_text.text` items and exact marker match, handling malformed or missing parts fail closed.
- Add a single synthetic canary evaluator whose PASS requires exactly one `read_file({"path":"CANARY.txt"})`, correct call_id/mediator count, allowed replay inputs, real second-turn continuation, terminal completed, marker in canonical final assistant text, and no disallowed tools. Wrong path, duplicate read, zero tool, missing marker, malformed output, incomplete replay must be FAIL, not an inferred success.
- Keep the authoritative EpisodeOrchestrator/DeepSeekRequestBuilder/BudgetEnforcer/replay path. Use fake provider responses for entire offline flow, not only inspection of source text.
- Correct frozen task quotation/backtick punctuation and explicitly record task/hash change from the prior unexecuted harness.
- Keep production retry backoff real; prove with an injected fake sleeper/clock and actual orchestrator retry events, not only a source-code substring test.

### B4. Tests do not yet demonstrate the claimed behavior

`test_old_api_calls_schema_mismatch_reproduced_and_fixed` only asserts that `api_calls` is absent; it does not reproduce the historic `KeyError`. `test_primary_audit_survives_derived_summary_failure` manually appends a fake provider_result event and then passes an invalid dict; it does not run the actual preflight persistence path or inject a failure after a real fake provider result is observed. `test_canary_production_path_does_not_inject_noop_sleep` merely searches source text. There are no tests of the full canary status gate.

**R2 required tests**:
1. Explicitly reproduce old `KeyError("api_calls")` offline from legacy dict access and show new schema handler works.
2. Model-list mock HTTP request once; capture actual transport attempt count and verify no hidden SDK retry on a synthetic retryable response.
3. Durable audit event exists before simulated request; observed response survives forced derived-summary exception.
4. Sanitizer rejects/redacts synthetic Authorization/Bearer/API key in each audit path.
5. A canary cannot launch if no persisted, verified preflight PASS evidence; no terminal automatic rerun.
6. A full fake DeepSeek two-turn tool/replay flow produces PASS only with the exact allowed tool/path/marker, and emits accurate accounting; illegal branches FAIL.
7. A live-path retryable simulated SDK error observes proper backoff via injectable clock/sleeper, without changing frozen RetryPolicy.
8. CLI offline-selftest is nontrivial and fails for corrupted fake evidence.
9. Existing DS-1 original result five files and DeepSeek/STATS protocols unchanged; no benchmark import/network/credentials.
10. Full regression green.

## Preserved constraints and artifacts

Retain the accepted provider protocol unchanged:
`sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`.

Retain the accepted statistical protocol unchanged:
`sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`.

Do not modify `src/researchci/**`, `src/researchci_agent/**`, scenarios, workspaces, manifests, C001–C006/A0–A4, DeepSeek adapter/provider protocol, statistical analysis, frozen system prompt/tool schema, any historical OpenAI or failed DS-1 reports.

Allow narrow changes to `agentbench/deepseek_live_canary/**`, a separate R2 offline test module (or R1 tests), and new `phase2b_ds1_r2_*.json` reports. Do not overwrite R1 reports.

Preserve the previous failure classification `FAIL_PREFLIGHT_ARTIFACT`; historical model presence/auth/status/request count remain unknown.

## Exit condition

- ZERO credential reads, ZERO DeepSeek/OpenAI API calls, ZERO network, ZERO real live episodes and benchmark episodes.
- New R2 reports: diagnostic, offline_e2e, regression, scope_audit, harness_freeze (including before/after task, serializer/audit hashes).
- Commit/push main; clean worktree and `HEAD == origin/main`; output exact SHA and evidence; STOP.
- **No replacement `GET /models` is authorized by this amendment.** Planner must accept R2 and separately authorize any next live attempt.
