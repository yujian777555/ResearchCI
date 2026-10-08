# Phase 2B-DS-1-R1 — Offline Recovery of Preflight Evidence and Live Harness Reliability

**Status:** PLANNER SPEC / OFFLINE REPAIR ONLY

**Context / accepted lineage**
- DS-1 Planner: `docs/PHASE2B_DS1_PLAN.md`, `f62e6d2da69339378d3e12394ab1cbc6ce64a519`
- pre-network harness commit: `128758327f8f1b85bc1d73c98339702a691634d7`
- failed result commit: `d92b541263edea9b749ff70f475fc4aad5b2fce0`
- DeepSeek DS-0-R1 provider protocol (immutable): `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`
- STATS-0-R1 (immutable): `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`

## 1. Evidence classification

The committed DS-1 result is **FAIL_PREFLIGHT_ARTIFACT / INFRA_INVALID_ARTIFACT**. One `client.models.list()` SDK invocation is reported. Its actual wire-level request count, HTTP/provider status, request ID, UTC timestamps, and whether the model list included `deepseek-v4-pro` are **not verifiable** from preserved artifacts.

A local `KeyError('api_calls')` during result serialization prevented persistence of provider outcome. This is **not evidence of invalid DeepSeek credentials, of model absence, or of ResearchCI model behavior**. No Responses call and no live canary took place.

The initial attempt remains permanently preserved. Neither retrospectively claim its preflight PASS nor delete/overwrite its evidence.

## 2. Scope of R1

R1 is **strictly offline**. Fix only:
1. deterministic, tracked, auditable DS-1 preflight/canary entrypoint and result serialization;
2. loss-resistant sanitised preflight event capture with distinguishable SDK invocation versus actual HTTP attempts;
3. live canary retry backoff semantics;
4. narrow offline tests/regression/hashes/reports.

R1 **must not** execute a replacement preflight or a live canary. A subsequent separate Planner authorisation is required for any second `GET /models` request.

## 3. Root-cause reproduction first

Locate the exact local execution/serializer that threw `KeyError('api_calls')`. If it was an untracked script or one-off terminal command:
- state that fact explicitly;
- preserve its available non-secret source/command and sanitized exception details in an R1 diagnostic report, or state if the exact source cannot be recovered;
- do not invent the lost provider response or reconstruct missing HTTP status/timestamps.

Reproduce the failure deterministically offline with a fake preflight result. Establish the actual schema mismatch (e.g. field `requests` versus `api_calls`) and fix at a single authoritative serializer/schema boundary.

## 4. Checked-in canonical entrypoint

Introduce a checked-in, reproducible DS-1 CLI/module entrypoint with narrowly separated modes:
- `offline-selftest`: only local fake transport and fixture;
- `preflight`: not executable in R1; future version must require an explicit live-authorization flag AND a frozen pre-network harness commit gate;
- `canary`: likewise disabled during R1; must refuse to run unless preflight PASS evidence is authenticated/present in the same authorised run.

No ad-hoc notebook, shell inline script, or untracked file may implement the authoritative live transition in later phases.

The entrypoint must fail closed: exceptions during serialization/reporting cannot be interpreted as provider success and cannot trigger automatic preflight/canary retry.

## 5. Exact transport accounting and crash-safe audit

Preflight must explicitly distinguish:
- `sdk_invocations`;
- `http_attempts_observed`;
- `http_attempt_count_verified`;
- `responses_http_attempts_observed`;
- `provider_outcome_observed`;
- `provider_outcome_persisted`.

Use an injectable transport / HTTP client instrumentation to count actual HTTP request attempts. Disable implicit OpenAI SDK retries for preflight (`max_retries=0`).

For future real events, commit a structured, sanitized append-only local event record **before** any derived summary serializer can fail. Record:
- preflight_start UTC (before request);
- transport_attempt/response/error UTC as observed;
- completion classification;
- target id presence (not full model catalog);
- request id/status if available;
- credential presence boolean, never secret;
- non-empty semantic evidence distinguishing `UNKNOWN` from `False`.

Crash consistency:
- atomic file replacement for derived JSON summaries;
- append-only, durable sanitized primary event evidence for each significant transition;
- serialize from a schema-validated dataclass or typed result rather than accessing arbitrary undocumented keys.
- A forced derived-report serialization failure must not erase already-observed provider result / preflight metadata.
- No logs containing full headers or SDK request object dumps.

No unsupported assertion of the count of wire requests. If HTTP instrumentation fails, record `UNKNOWN / unverified`, STOP and report it.

## 6. Retry/backoff correctness

Current `agentbench/deepseek_live_canary/canary.py` injects `sleep=lambda _:None` into the shared orchestrator. This would bypass the accepted bounded real-time retry backoff.

Change the **DS-1 canary harness only** so the production/live path uses genuine `time.sleep` (or the orchestrator default sleep). An injected no-op sleep is allowed only inside explicit offline tests.

Ensure OpenAI-compatible SDK implicit retries are disabled for the canary client so all intended Responses retries are visible to the authoritative orchestrator and frozen RetryPolicy. No retry protocol values change.

Offline test a synthetic retryable error and prove the production canary glue does not silently skip the frozen backoff delay. Use a controllable fake sleeper/clock in tests instead of waiting in real time.

## 7. Canary qualification contract regression

R1 does not run real canary. Add offline fake-provider tests of:
- task exactness against `docs/PHASE2B_DS1_PLAN.md` including its punctuation/backticks;
- frozen marker `RESEARCHCI_DEEPSEEK_CANARY_OK_DS1`;
- read_file exactly once and only exact path `CANARY.txt`;
- use of the same authoritative `EpisodeOrchestrator` / BudgetEnforcer / projection path;
- exact tool `call_id` and stateless replay;
- canonical assistant `output_text` extraction (not Python `str(list)` for message contents);
- canary FAIL classification if extra tools, zero tool, wrong path, marker absent, replay invalid or model output incomplete;
- local result serializer never mistakes missing fields for success;
- zero benchmark/scenario loaded.

If a previously frozen canary task string differs in punctuation from the Planner's exact task, explicitly document/rectify the harness task representation BEFORE ANY successful live canary. The original unexecuted task and previous harness hash remain in Git history. This is a new versioned harness, not a retrospective mutation.

## 8. Frozen boundary

Forbidden changes:
- `src/researchci/**`, `src/researchci_agent/**`, C001-C006, A0-A4;
- Phase 1 / Phase 2A scenarios, workspaces or manifests;
- `agentbench/deepseek_adapter/**`, `agentbench/deepseek_protocol/**`;
- accepted DeepSeek DS-0-R1 provider contract/protocol hash;
- `agentbench/analysis/**` and STATS-0-R1 analysis contract;
- system prompt and tool schema semantic content;
- historical OpenAI/DeepSeek reports, earlier failed DS-1 result files.

Allow narrow changes only in `agentbench/deepseek_live_canary/**`, new DS-1-R1 tests, and new R1-specific reports.

## 9. New R1 evidence (never overwrite DS-1 failure)

Add:
- `agentbench/reports/phase2b_ds1_r1_diagnostic.json`;
- `agentbench/reports/phase2b_ds1_r1_offline_e2e.json`;
- `agentbench/reports/phase2b_ds1_r1_regression.json`;
- `agentbench/reports/phase2b_ds1_r1_scope_audit.json`;
- `agentbench/reports/phase2b_ds1_r1_harness_freeze.json`.

Freeze hash of the revised harness sources, retry policy reference, canary task/marker, fixed serializer schema, preflight audit contract and relevant tests.

Reports should explicitly reference immutable first DS-1 harness/result commits and classify that attempt as `FAIL_PREFLIGHT_ARTIFACT`; neither infer credentials validity nor replay the historical request.

## 10. Tests / acceptance

Add deterministic offline tests verifying:
- `api_calls` schema-mismatch failure reproduced and fixed;
- missing or mistyped field causes explicit local serialization failure, not a second network call;
- provider result stays available if derived summary serialization fails;
- preflight FAIL/target absent/target present/response missing all produce distinct outcomes;
- exactly one observed transport attempt is distinguished from exactly one SDK method call;
- implicit SDK retries disabled in future credential/model preflight;
- no automatic canary after failed/unpersisted preflight;
- canary live backoff is non-noop and runtime retries remain frozen;
- exact canary behavior gates;
- no secret contents in local event or derived audit;
- old DS-1 failure untouched;
- full historical regression green.

**No credential read and no runtime network in R1.**

## 11. Stop

Complete full regression, write new R1 reports, commit/push, verify clean `HEAD == origin/main`, then **STOP**.

No replacement `GET /models`, no `POST /responses`, no synthetic live canary, no 270-episode pilot, no formal study.

Planner will inspect GitHub and decide whether to pre-register exactly one additional non-generative replacement preflight in a later DS-1-R2 phase. That replacement cannot be treated as the original “first request,” and must not be run without explicit authorisation.
