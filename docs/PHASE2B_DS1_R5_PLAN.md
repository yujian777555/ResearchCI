# Phase 2B-DS-1-R5 — Controlled Live-Transport Cutover (OFFLINE PREPARATION ONLY)

**Planner status: OFFLINE IMPLEMENTATION AUTHORIZED; LIVE REPLACEMENT PREFLIGHT NOT AUTHORIZED.**

## Baseline and immutable evidence
- R4 accepted offline harness: `01fe25f10bb6f5001054652a975161abf9eebfc5`.
- Historical first DS-1 preflight (FAILED ARTIFACT): harness `128758327f8f1b85bc1d73c98339702a691634d7`, result `d92b541263edea9b749ff70f475fc4aad5b2fce0`.
- Accepted DeepSeek DS-0-R1 execution protocol: `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`.
- Accepted statistical protocol: `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`.

R4 validated real OpenAI-compatible SDK calls through in-memory HTTPX2 MockTransport. It **does not** prove credential access or genuine network compatibility and intentionally cannot perform real network requests. R5 implements a separately gated real-transport cutover with offline tests; STOP before any real request.

## 1. No network in R5
- Real DeepSeek API calls = 0.
- Real OpenAI API calls = 0.
- External provider network calls = 0.
- Real credential/environment key reads = 0.
- Real canary episodes = 0; benchmark episodes = 0.
- Do **not** use curl, SDK or HTTP to test GET /models or POST /responses.
- Do not ask Codex to run live preflight just because R5 offline tests pass.

## 2. Scope
May change narrowly `agentbench/deepseek_live_canary/**`, add R5 offline tests and **new** `agentbench/reports/phase2b_ds1_r5_*.json`.
Do not change ResearchCI core, C001–C006, A0–A4, scenarios/manifests/workspaces, DeepSeek DS-0-R1 adapter/protocol, STATS analyzer/protocol, system prompt/tool schema, or any historical DS-1 failed/R1/R2/R3/R4 report.

## 3. Real transport must share precisely the R4 audited SDK wire path
- Make the DS-1-owned `AuditedSDKTransport` work with an actual `httpx2.HTTPTransport` (or explicitly verified equivalent) as well as R4 MockTransport. Retain the **same** `models.list` and `responses.create` SDK clients and audit event machinery; do not create an ad hoc live path or switch SDK interfaces.
- Maintain `https://api.deepseek.com`, exact endpoint allowlist, SSL/TLS validation, `trust_env=False`, explicit bounded timeouts, `max_retries=0`, no HTTP transport retries, no silent redirects.
- The live transport factory is **disabled by default** and cannot read environment variables. Constructing it requires an explicit future run authorization object scoped to one stage and immutable harness commit; this R5 stage has no such authorization.
- The operator-supplied API key must only be read after **separate human approval**, from an out-of-repo secure environment; never print, return, serialize, hash, or log it. Do not read it in R5. All R5 fixtures use a fixed synthetic test string.

## 4. Freeze an intentional one-request run ledger; do not use mutable booleans as authorization
- Persist pre-network status/immutable execution intent for one `GET /models` replacement attempt, distinguish it from original unknown-outcome attempt.
- Before any later live request, verify pre-registered harness SHA, `HEAD==origin/main`, clean worktree, the operator-approved run ID, and `DEEPSEEK_API_KEY` presence only (not value in reports).
- Validate one-use token/ledger with atomic reservation **before HTTP** and no automatic rerun after crash/timeout.
- Record audited HTTP transport attempt counts and resulting sanitized model presence/status, not raw headers/full catalog.
- Historical first attempt remains `FAIL_PREFLIGHT_ARTIFACT`, its wire count, auth/model presence UNKNOWN.
- Approval of preflight does **not** approve `POST /responses` or canary; preflight result must be pushed/sanitized and reviewed by Planner first.
- Distinguish external transport counters from fake/logical SDK counters and fail closed when instrumentation is missing.

## 5. Offline production-path dress rehearsal
Use exactly the same factory and state transition functions intended for later real use, but inject `httpx2.MockTransport` and synthetic key in tests.
- Simulate a future one-time authorisation token/approved-harness-SHA in tests only; do not commit a valid real authorization artifact.
- Prove expected-denied cases (unapproved, wrong SHA, dirty worktree, already claimed token, wrong stage, wrong run ID, preflight failed, unknown HTTP attempt count, post-crash restart).
- Verify single real-SDK `GET /models` request with audited wire count on allowed synthetic test fixture and no hidden SDK retries.
- Verify no `POST /responses` from the preflight-only stage, even on PASS.
- Test 200 target/absent, 401, 402, 429, 500/503, timeout, interrupted process, malformed, and serializer crash; always zero real network.
- Confirm frozen provider/stats hashes and full regression unaffected.

## 6. New frozen artifacts and stop
Add new `phase2b_ds1_r5_diagnostic.json`, `phase2b_ds1_r5_offline_e2e.json`, `phase2b_ds1_r5_regression.json`, `phase2b_ds1_r5_scope_audit.json`, `phase2b_ds1_r5_harness_freeze.json`.

Report immutable baseline, source/client/transport/ledger/schema hashes, synthetic mock attempt counts, freeze evidence and **zero external network/API/real credential**.

Commit/push R5 harness to main; verify clean `HEAD==origin/main`; **STOP**.

Only after Planner's R5 code review AND explicit new human approval may a separate action enable exactly one **replacement** `GET /models`. That later action must first reverify the frozen harness commit and one-use ledger. The preflight outcome is recorded/pushed and STOPs pending another Planner decision. The eventual synthetic live canary requires another explicit approval; no 270-episode pilot/formal experiment is authorized here.
