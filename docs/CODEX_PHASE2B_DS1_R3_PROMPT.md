# ResearchCI Codex Executor Prompt — Phase 2B-DS-1-R3

你是 ResearchCI Executor，ChatGPT 是 Planner。你必须直接同步 GitHub 实际状态、严格实现指定 **离线** R3，然后提交并 STOP。

## Authority
- Repo: https://github.com/yujian777555/ResearchCI
- Branch: main; Issue #15
- Planner authoritative spec: `docs/PHASE2B_DS1_R3_AMENDMENT.md`
- Planner amendment commit: `73228cb4f2f69ecd135239eb23d9073079d51867`
- R2 to repair: `081bccd3ef3f1f88e00fa5b2cdf4184edb3f0a37`
- Frozen DS-0-R1: `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`
- Frozen STATS-0-R1: `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`

If instructions differ from the repo Planner amendment, the amendment takes precedence.

## First read, then test, then repair

```
git fetch
git pull --ff-only
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Require clean HEAD=origin/main. Read the complete amendment, original DS-1 task, R2 code/reports, DeepSeekRequestBuilder, DeepSeekResponsesAdapter, FakeDeepSeekResponsesAdapter, EpisodeOrchestrator and their tests.

Before implementation, add deterministic red tests that demonstrate the four verified production-parity gaps:

### A. Real DeepSeek adapter can NEVER get PASS in current canary

Current `run_canary` has hard-coded fake accounting:
`live_api_calls==0 and network_calls==0 and fake_provider_calls>=1`.
With a real `DeepSeekResponsesAdapter` and an **injected fully in-memory mock /responses transport**, a valid two-turn sequence must be recognized as **SIMULATED_LIVE_ADAPTER_OFFLINE / qualified behavior PASS**, not failed merely for nonzero adapter live/network counters.

Do not claim those counters mean real external network was used. Separate adapter logical counters from actual external wire requests. New canary evaluation must support both adapter kinds while preserving identical semantic gate checks. Exactly two successful provider responses, only one valid tool read, correct final marker, no extra behavior. Test fake and live-adapter-with-mock paths.

### B. Replay audit cannot rely on `FakeAdapter.requests`

Real `DeepSeekResponsesAdapter` does not expose `requests`. Introduce a DS-1-only observational adapter wrapper that captures in-memory submitted request structures/hashes at `create_response` without mutating data or changing error/retry/accounting semantics. Verify original task, stateless projected reasoning/function call, exact call_id and function_call_output, correct order, and rejected forbidden output-only fields.

Add positive replay tests through real DeepSeek adapter + injected offline fake transport, and negative tampered-replay tests. **Do not edit frozen adapter, orchestrator or provider protocol.** Do not persist full reasoning text, request contents, key or headers.

### C. Model-list preflight must instrument the actual SDK wire path

Handwritten `OfflineModelListClient` + direct `TransportAudit.before_attempt` is not enough for real production-path parity.

Build a disabled-by-default DS-1-owned audited HTTPX transport/client factory compatible with actual OpenAI SDK `models.list`, `max_retries=0`, transport retries=0. Its real code path must accept a supplied credential only in a **later** separately approved live phase. **R3 cannot read user key or access real internet.**

Use injected `httpx.MockTransport` in offline tests to exercise the *same SDK client construction and transport instrumentation* for 200 target present, 200 target absent, 401, 429, 503, timeout, malformed response, and derived serializer crash. Audit preflight_start, HTTP attempt, response/error, observed outcome, persisted outcome, and original counts; append/fsync sanitized primary events before derived summary. Distinguish SDK invocations, observed wire attempts, verified count, logical /responses calls. Error/unknown cases must fail closed without automatic retry.

If actual SDK dependencies prevent this, explain the blocker, do not substitute a homemade fake as production proof.

### D. Persisted-pass gate must verify actual persisted records

Today any code can pass a forged `dict` with five PASS flags to `QualificationGate`. It checks claimed values but not whether same-run primary evidence exists.

Implement per-run identity, ordered primary event records with integrity checks/read-back, and exact summary/primary evidence correspondence. Only an audited and durable same-run PASS (target true, one verified wire request, no hidden retry) may be consumed **once** to admit the synthetic canary. Reject forged dict, missing log, tampered file, duplicate/ambiguous run, wrong ID, previously consumed entry and unpersisted outcome. Design an explicit single-run session state; don't overclaim protection from intentional privileged file tampering.

### E. Behavioral gate tests

Keep original exact `TASK` including backticks and marker. Check actual `output_text.text`, exactly one `read_file({"path":"CANARY.txt"})`, call-id preservation, correct second request replay, final completed response and valid model id. No tool, wrong tool/path, duplicate tools, malformed/refusal/empty final response, fake-only accounting in live mode and tampered replay must all FAIL. Retry 429/503 with injected sleeper verifies existing 1s/2s policy, no token/step budget reset, no reexecution of earlier tool.

CLI `offline-selftest` must run actual fake preflight + fake and simulated-live-adapter canary flows and fail for corrupt primary evidence. CLI `preflight` and `canary` must **remain disabled** with nonzero exit codes. Preserve old DS-1 failure and R1/R2 reports untouched.

## Hard scope
Allowed only:
- `agentbench/deepseek_live_canary/**`
- new or revised DS-1-R3 offline tests
- **new** `agentbench/reports/phase2b_ds1_r3_*.json`

Forbidden all core ResearchCI / Agent runtime, Phase 1/2A scenarios/manifests/workspaces, DeepSeek adapter/protocol files, frozen STATS analysis, prompts/tools, any historic failed result or earlier frozen report. STOP if forbidden change required.

## Required output/reports
Create 5 new JSON reports:
- `phase2b_ds1_r3_diagnostic.json`
- `phase2b_ds1_r3_offline_e2e.json`
- `phase2b_ds1_r3_regression.json`
- `phase2b_ds1_r3_scope_audit.json`
- `phase2b_ds1_r3_harness_freeze.json`

Freeze revised harness source, SDK client/transport implementation, audit and serializer schema, exact canary task/marker, test/source hashes, DeepSeek/STATS protocol hashes. Document all negative tests, simulation vs real network accounting, and historic failed preflight (status/model presence/wire count UNKNOWN).

Run `pytest` full regression, 0 failures. **No actual external network calls, no DEEPSEEK_API_KEY/OPENAI_API_KEY reads, no GET /models, no POST /responses, no real canary or benchmark.**

Commit: `Phase 2B-DS-1-R3: verify production-parity qualification path offline`.

Push main, verify remote SHA and clean worktree. Return concise completion report with commit, per-area tests, real-SDK MockTransport counts, canary fake vs simulated-live outcomes, persisted gate rejection matrix, frozen hashes, audits, zero real-network/API/credential/live/benchmark counts, unresolved deviations.

**STOP. Do not close Issue #15 and do not authorize a replacement preflight. Planner will review.**
