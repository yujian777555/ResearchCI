# Phase 2B-DS-1-R4 — Pre-Live Activation Harness Freeze

Status: **Planner stage authorized for OFFLINE IMPLEMENTATION ONLY. NO LIVE REQUEST YET.**

## 0. Lineage and decision

- Accepted R3 implementation: `cc9ccc6458c5fe70e6650ade9f752d2a765e705a`
- Historical first DS-1 harness: `128758327f8f1b85bc1d73c98339702a691634d7`
- Historical first DS-1 failure: `d92b541263edea9b749ff70f475fc4aad5b2fce0`, `FAIL_PREFLIGHT_ARTIFACT`
- Accepted DeepSeek protocol: `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`
- Accepted STATS protocol: `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`
- R3 revised offline harness source: `sha256:30e31b22d048df6ac8129ba65a34da076926284455d84a809165d3c496cc33b2`

R3 is accepted as an offline harness. It did not verify actual DeepSeek authentication, model availability or remote Responses compatibility. Both CLI live modes remain disabled.

**R4 objective:** build and freeze the **real DeepSeek SDK-based** preflight and Responses canary activation layer, test it against the exact same SDK clients with in-memory HTTP mock transport, and STOP **before** making another real network request.

Any follow-up release of a replacement preflight is a distinct Planner decision after R4 review. A second `GET /models` is not authorized in R4.

## 1. Scope

Allowed:
- `agentbench/deepseek_live_canary/**`
- new R4 offline tests
- new `agentbench/reports/phase2b_ds1_r4_*.json`

Forbidden:
- core `src/researchci/**`, `src/researchci_agent/**`
- Phase 1/2A scenarios/workspaces/manifests, C001–C006, A0–A4
- `agentbench/deepseek_adapter/**` and frozen provider contract/protocol
- `agentbench/analysis/**` and frozen statistics
- frozen system prompt/tool schema
- all historical OpenAI and DS-1 failed/R1/R2/R3 evidence

No actual DeepSeek/OpenAI API calls, no external network, no reading `DEEPSEEK_API_KEY`/`OPENAI_API_KEY`, no live canary, no benchmark episodes.

## 2. A single checked-in production client/transport construction path

Implement a DS-1-owned client factory with clearly separated:
- preflight OpenAI-compatible SDK `models.list` client;
- DeepSeek Responses client used by the frozen `DeepSeekResponsesAdapter(client=...)`.

Both must:
- use frozen `https://api.deepseek.com` base URL, exact model `deepseek-v4-pro`;
- use verified `max_retries=0` SDK transport to prevent hidden retries;
- have bounded, explicit timeout matching frozen budget constraints (without modifying budgets);
- opt out of system proxy/environment transport surprises where feasible (`trust_env=False`);
- use DS-1-audited underlying HTTP transport so SDK `models.list` and `responses.create` wire attempts can be counted separately;
- never persist secret values, headers, full reasoning, or full model list.

Use installed HTTPX-compatible SDK supported interface; verify whether `httpx2` is the actual SDK dependency (the R3 repo reports SDK `openai==3.24.0`, `httpx2==2.13.1`). Do not assume `httpx` or `httpx2` will work without running type-accurate mock integration. For R4, supply only deterministic synthetic keys to tests. The future operator supplies the actual key from a safe environment after separate Planner authorization.

The current R3 preflight factory rejects any un-injected transport, which is appropriate for R3. R4 may introduce a **separately gated production transport factory**, but the CLI's live modes must remain disabled until a subsequent explicit activation grant. If there is no compatible transport, fail closed rather than substitute an unobservable client.

## 3. Full HTTP-mock SDK → Frozen Adapter → Orchestrator → Mediator → SDK replay test

R3's canary tests use `DeepSeekResponsesAdapter(transport=lambda ...)`. That tests adapter/orchestrator but **not** OpenAI SDK `responses.create()` serialization/decoding.

Add R4 **real SDK with MockTransport** two-turn E2E:
- initial provider response: frozen DeepSeek Responses-shaped JSON with assistant reasoning and one `function_call` with nonempty exact call_id and `read_file({"path":"CANARY.txt"})`;
- capture the exact POST /responses request JSON on the mock wire;
- continuation response: Responses-shaped JSON assistant `output_text.text` containing the exact marker;
- check that second request is full-history stateless replay with exact provider item projection + `function_call_output`, same call_id, and no `previous_response_id`, `store`, `conversation`, `metadata`, `parallel_tool_calls`, `temperature`, `seed`;
- validate frozen `deepseek-v4-pro`, `reasoning.effort=max`, `top_p=.95`, tool schema, dynamic max_output_tokens, 30/20/900/16k budgets;
- verify 2 successful Responses SDK calls, exactly one mediator read, no extra tool, deterministic request/response accounting, exact marker and PASS classification;
- normalize 400/401/402/422/429/500/503/timeout/connection with frozen error mapping; test no SDK hidden retries while orchestrator retries are observable when allowed;
- do not tune protocol or request schema after seeing a real provider outcome.

All HTTP handled by `httpx2.MockTransport` (or exact installed SDK equivalent). Actual external network 0; original historical DS-1 evidence unchanged.

## 4. Preflight audit and qualification gate final checks

- Keep the verified R3 audited `models.list()` transport and single-use `QualificationGate`.
- Wire it to the same DS-1 client factory used by R4, not a second invented client.
- Ensure HTTP start/attempt/response/error records are append+fsync and type/sanitize protected.
- Enforce preflight pass only if target model is present, actual SDK HTTP attempt count exactly 1, retries disabled, primary evidence was written and verified, and summary matches the same run.
- Do not unlock canary solely from a manually constructed PASS dictionary.
- Explicitly test abnormal process termination and crash during derived summary: no automatic retry, no canary, evidence survives.
- Distinguish provider outcome UNKNOWN from absent/invalid credentials.
- Record one historical failed SDK call from the first DS-1 run as a separate immutable predecessor; never call it a successful original preflight.

## 5. Live activation remains DISABLED in R4

The CLI's `preflight` and `canary` modes must both return a nonzero status. A future approved executor may only enable them with a separate versioned authorization, fresh commit hash after full offline tests, pre-network clean worktree, human-supplied credential and one-use persisted execution ledger.

No R4 code/test/report may claim a new real preflight or canary has occurred.

## 6. Required tests and reports

Add deterministic regression for:
1. exact production SDK client construction with synthetic key; `max_retries=0`, no hidden HTTP retries;
2. audited GET /models through installed SDK and HTTP mock, all target/HTTP error outcomes;
3. 2-turn POST /responses via actual SDK, frozen adapter, orchestrator, projection, mediator and full HTTP-body inspection;
4. real SDK response Pydantic decode, complete model/usage/item shapes; malformed/refusal/no-tool/extra-tool/invalid-replay cases fail closed;
5. retry 429/5xx with real SDK mock and frozen orchestrator backoff (no double retries);
6. durable same-run gate, tamper/restart/duplicate/missing outcome;
7. primary audit survives injected derived serialization crash;
8. no reading user credentials, no external network;
9. old DS-1 and R1-R3 reports unchanged, DeepSeek/STATS hashes unchanged.

New reports:
- `agentbench/reports/phase2b_ds1_r4_diagnostic.json`
- `agentbench/reports/phase2b_ds1_r4_offline_e2e.json`
- `agentbench/reports/phase2b_ds1_r4_regression.json`
- `agentbench/reports/phase2b_ds1_r4_scope_audit.json`
- `agentbench/reports/phase2b_ds1_r4_harness_freeze.json`

Freeze revised harness/client transport source hashes, actual SDK dependency versions, exact fixture/task, provider contract/statistics hashes, and the permitted future request counter definitions.

## 7. Exit and later network authorisation

Full `pytest` green, no independent network/key access, all new audit reports PASS, commit/push `main`, confirm `HEAD==origin/main`, working tree clean, then STOP.

**No replacement GET /models yet.** Planner reviews R4 actual code first, then may issue a distinct authorization for **exactly one replacement, non-generative GET /models**. Only if that new preflight returns securely persisted PASS and includes `deepseek-v4-pro` may a single synthetic non-benchmark canary be authorized. No 270-episode pilot or formal study until separate review.

Do not close the next R4 issue yourself.
