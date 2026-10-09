# Phase 2B-DS-1-R3 — Offline Production-Parity Qualification Gate

**Status: Planner-required offline integration repair.** Reviewed R2 commit: `081bccd3ef3f1f88e00fa5b2cdf4184edb3f0a37`.

Prior R2 plan: `docs/PHASE2B_DS1_R2_AMENDMENT.md`. Issue #15 stays OPEN. This is **not** another research redesign. DeepSeek DS-0-R1 and STATS-0-R1 stay frozen.

## Review decision

R2 made substantial valid offline progress (typed primary audit, fake end-to-end tool/replay, positive and negative CLI selftest, exact task punctuation). **It is not production-parity safe yet.**

### Blocker 1 — fake-only canary PASS predicate

Current `agentbench/deepseek_live_canary/canary.py` computes:

```python
accounting_valid = result.live_api_calls == 0 and result.network_calls == 0 and result.fake_provider_calls >= 1
```

Therefore a successful actual `DeepSeekResponsesAdapter` run, with live API calls and zero fake calls, can never PASS. The canary's PASS criteria must be provider-neutral for scientific behavior and independently validate accounting according to explicit *fake* and *live* modes.

**Fix:**
- The same tool/replay/marker/termination gates must work with `FakeDeepSeekResponsesAdapter` and `DeepSeekResponsesAdapter` using an injected offline mock transport.
- For actual live mode require `fake_provider_calls=0`; expect valid positive `live_api_calls` and `network_calls`, with provider retry accounting consistent. Do not demand live/network=0 in live mode.
- For offline fake mode require zero live/network and positive fake calls.
- Never pass or infer real API execution solely because an injected fake transport increments adapter counters: label this `SIMULATED_LIVE_ADAPTER_OFFLINE`, with zero actual external HTTP.
- Verify exactly two successful responses (one tool-turn and one final-turn); any extra tool, missing response, invalid model result, or unrecognized response structure fails.

### Blocker 2 — replay validation is fake-adapter-only

Current code reads:

```python
adapter_requests = list(getattr(adapter, "requests", []))
```

The frozen real `DeepSeekResponsesAdapter` does not expose a `requests` list; it sends requests through `create_response` and only the Fake adapter stores them. Thus even correct live replay is marked `replay_valid=False`.

**Fix:**
- Add a narrowly scoped observational wrapper in the DS-1 harness that records *in-memory* request structure and immutable hashes at the `create_response` boundary for both adapters, without altering request content or the accepted DeepSeek provider implementation. Do not persist full reasoning/request bodies or credentials.
- Audit first-turn initial task, second-turn projected provider reasoning/message/function-call, exact `call_id`, exact function output, ordering, and absence of forbidden response-only metadata.
- Ensure wrapper does not change counters, adapter identity, exceptions, retries, tool mediation, or budgets. Run both fake-adapter and real-adapter-with-fake-transport E2E tests through the authoritative orchestrator.
- Request structural checks must not rely on `FakeDeepSeekResponsesAdapter.requests`.

### Blocker 3 — preflight wire instrumentation is disconnected from real SDK

Current `TransportAudit` is invoked manually by `OfflineModelListClient`, and there is no audited OpenAI-compatible SDK client factory or `httpx` transport wrapper on the production path. A fake client calling audit methods proves the fake class's behavior only. It does not prove `client.models.list()` will generate exactly one actual HTTP request with hidden retries disabled.

**Fix:**
- Build a *disabled-by-default*, checked-in DeepSeek preflight client factory wired to an actual HTTPX request transport/transport adapter and OpenAI-compatible SDK `models.list()`; set SDK `max_retries=0`, transport retry=0. In R3, tests must inject `httpx.MockTransport` into this **same production client construction path**, so no packets leave the process.
- Instrument attempted HTTP requests at the actual HTTP transport boundary; persist sanitized preflight start/attempt/success/error events. `http_attempt_count_verified=True` only when a real instrumented transport has recorded exactly one attempt and a corresponding completion, plus a durable primary outcome event.
- Exercise 200 with target model, 200 without target, 401, 429, 503, network timeout and forced derived-summary crash. Assert SDK calls vs HTTP attempts separately and `max_retries=0`; no implicit repeat even on 429/503.
- If a real SDK client is not available in the environment, fail closed and document the limitation, **do not claim production-parity PASS**.
- Credential values must never be accessed in R3; future factory should accept a secret supplied through a separately authorised live entrypoint, not obtain it implicitly or log it.
- `preflight` and `canary` CLI modes must remain disabled in R3.

### Blocker 4 — canary gate trusts caller-provided claims of persistence

`QualificationGate.admit_preflight()` accepts an arbitrary dict and `canary_eligibility()` checks its claimed booleans. A caller can construct `{status:PASS,target_present:true,http_attempts_observed:1,http_attempt_count_verified:true,provider_outcome_persisted:true}` without any primary audit log or same-run evidence. This is a state gate, not a persisted provenance gate.

**Fix:**
- Introduce per-run ID/immutable attempt ID, checked-in audit schema, event ordering/integrity checks, read-back of durable primary evidence, exact relation to the persisted typed summary, and a separate single-use canary admission token/state restricted to the same run.
- Test forged in-memory PASS dict, tampered event log, missing result, unpersisted outcome, wrong run id, duplicate consumption, and process-restart attempt: all must fail closed.
- Do not claim cryptographic security from a simple hash chain; this gate protects against accidental/inadvertent mismatch in the experiment harness, not a malicious actor controlling local files.

## Additional acceptance checks

- Frozen `TASK` includes backticks, marker `RESEARCHCI_DEEPSEEK_CANARY_OK_DS1`, exactly one `read_file({"path":"CANARY.txt"})` mediator invocation and `call_id` exact. Check `output_text` typed parsing and tool/runtime failure taxonomy.
- No false positives from `ProviderResponse.has_text_output()` when the final content is malformed/refusal/empty; independent canary evaluator must fail closed.
- Production backoff unchanged (orchestrator `time.sleep` default). Fake tests may inject a sleeper; ensure retry events and tool invocation count correct.
- Existing R2 fake CLI selftest remains substantive and negative corrupted evidence exits nonzero.
- Keep frozen budget/retry/system prompt/tool schema/model/sampling values and A0-A4/C001-C006 semantics unchanged.
- Do not introduce a live network-enabled code path in CLI now. Any future opening requires separate explicit Planner authorisation and a **new pre-network frozen harness commit**.

## Scope / evidence

Allowed: `agentbench/deepseek_live_canary/**`, new R3 offline tests, new `agentbench/reports/phase2b_ds1_r3_*.json`.

Forbidden: `src/researchci/**`, `src/researchci_agent/**`, Phase 1/Phase 2A scenarios/workspaces/manifests, `agentbench/deepseek_adapter/**`, `agentbench/deepseek_protocol/**`, `agentbench/analysis/**`, frozen prompt/tools, historical OpenAI/DeepSeek provider and canary evidence, DS-1 failure JSON, R1/R2 reports.

Accepted DeepSeek protocol: `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`.

Accepted statistics protocol: `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`.

Original failed `GET /models` evidence remains `FAIL_PREFLIGHT_ARTIFACT`, provider outcome and actual wire attempts UNKNOWN.

Create `phase2b_ds1_r3_diagnostic.json`, `phase2b_ds1_r3_offline_e2e.json`, `phase2b_ds1_r3_regression.json`, `phase2b_ds1_r3_scope_audit.json`, `phase2b_ds1_r3_harness_freeze.json` with source/SDK/transport schema/audit and canary task hashes, positive/negative behavior coverage, and 0 live/API/network/credential read/benchmark counts.

Run full pytest, confirm all previous tests green, commit/push main, `HEAD==origin/main`, clean, STOP.

**No new GET /models; no POST /responses; no real API key read; no real network; no live canary; no 270/900-episode study.** The human and Planner will separately decide whether to allow a replacement model-list preflight after inspecting R3.
