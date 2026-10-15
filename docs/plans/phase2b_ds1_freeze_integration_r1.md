# ResearchCI — Phase 2B-DS-1-LIVE-PREFLIGHT-FREEZE-INTEGRATION-R1 (Planner Plan)

**Status:** PLANNED / STRICTLY OFFLINE / LIVE NOT AUTHORIZED  
**Reviewed baseline:** `8947f7da6d38d70fd56a8c5a877fc397ed65e354`  
**Repo:** `yujian777555/ResearchCI`; `main`  
**Issue:** https://github.com/yujian777555/ResearchCI/issues/18

## 0. Verified facts / decision

Freeze R0 commit `8947f7d` adds three reports and one test; it sets candidate execution SHA `52a6437...`, records five historic artifact SHAs as stale, and correctly labels `CHAIN_INVALID`. Its eight hard-stop tests use a **test-local `hard_stop()` function**, not the production `execute_replacement_preflight` / `Reservation` / `build_sdk_client` admission path. Therefore hard-stop production integration is **NOT YET VERIFIED**. Executor reports `544 passed / 90 failed / 4 skipped` on Windows; not a passing full regression.

Existing production repository verification in `authorization.py::read_repository_state/validate_repository` requires the executing local branch `main`, local `HEAD`, `origin/main`, and a fresh authenticated `git ls-remote origin refs/heads/main` to equal the authorized harness SHA. Thus merely checking out a detached old SHA, switching branches, changing `require_fresh`, or accepting `HEAD != SHA` is **not** a valid workaround.

Current grant/approval remain HOLD, execution authorization is NOT_GRANTED, credential is NOT_ACQUIRED, provider calls 0. Historical rejected `FAIL_PREFLIGHT_ARTIFACT` evidence and protocol hashes must not be reinterpreted or altered.

## 1. Goal

Eliminate the **self-invalidating commit cycle** using a strict separation:
- **Code/protocol execution target S:** one clean, verified main commit that is finalized **after** all source/test/docs commits and **before** future operator authorization. Current R0 `52a6437...` is only a stale candidate; do NOT treat it as automatically accepted.
- **Offline technical plan and test fixtures:** can be committed before the final S is selected. Each commit then supersedes the candidate. That is expected, not a reason to emit another Grant.
- **Separate external per-run approval and authorization:** independently issued/signed only by an authorized human/operator, delivered to a protected location **outside the repo**, explicitly bound to S and all exact scope/run/ledger/runtime identities. NEVER commit, automatically sign, self-approve, or silently rebind a real grant.
- **Execution-side evidence/ledger:** durable on qualified native Linux FS outside the repo; `/tmp` suffices for tests but must not be presumed durable for live evidence. Operator chooses/qualifies real durable location later.

No new execution permission is granted by this plan.

## 2. Allowed work (offline only)

1. Review actual production repository admission and `execute_replacement_preflight`, `build_sdk_client`, `AuthorizationVerifier`, `OneUseLedger`, audited transport path and current reports.
2. Document lifecycle:
   - finish any code and docs changes → commit/push → remotely verify S → stop repository mutation;
   - operator later issues separately approved `PRECHECK_ONLY` signed v2 intent tied to S, `run_id`, `token_id`, `ledger_path`, expiry, DeepSeek `GET /models`, max 1, allowed `LIVE_HTTP`, exact trust anchor, runtime;
   - repository main and actual fresh remote main must remain S through the pre-wire gate, or STOP;
   - external signed approval and authorization may be read **only after separate explicit execution permission**; do not create production signing keys or approval in this task;
   - ledger ensures one reservation; do not retry on failures/uncertainty; evidence persisted/redacted off repo; commit reports **only after** future execution has ended and audit preserved.
3. Introduce an offline-only **independently testable integration check** using real production validation paths and injected synthetic states, ephemeral test keys, mock HTTP with socket guard. The test shall prove missing/stale/mixed/altered artifacts fail before any credential callback, production transport construction or wire attempt, and valid synthetic v2 policy reaches mock GET once while preserving LIVE security mode. Do not rely on a test-local `hard_stop` helper as a substitute for production gate coverage.
4. Where production code cannot accept external properly signed approved artifacts while retaining its existing remote-main predicate, report `BLOCKED_CONTRACT_GAP` with exact location; do not bypass the security contract. Do not use detached HEAD for live unless a **separately reviewed, independently tested contract revision** explicitly authorizes it (not in scope here).
5. Investigate Windows 90 regression failures as a distinct **open** issue and rerun relevant suite on qualified WSL2 Linux, with exact environment, exit codes, pytest collected/pass/fail/skip. WSL test dependencies may be missing; state `NOT_RUN/ENVIRONMENT_BLOCKED` if so. Do not declare all-green with any 90 failures, or silently fix frozen security core.
6. Reconcile signed intent `harness_sha` vs any document-only artifact `repository_sha`: the former is enforced by production; a plain JSON grant with `status=HOLD` is NOT a signed approval. Document final trust and signing authority separation. Avoid pretending historical HOLD is GRANTED.
7. Ensure historic freeze and earlier reports remain immutable; add only new phase-specific reports/tests, preserve DeepSeek hash `07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe` and STATS hash `e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`.

## 3. Required output

New:
- `agentbench/reports/phase2b_ds1_freeze_integration_r1_design.md`
- `agentbench/reports/phase2b_ds1_freeze_integration_r1_contract_audit.json`
- `agentbench/reports/phase2b_ds1_freeze_integration_r1_regression.json`
- `agentbench/reports/phase2b_ds1_freeze_integration_r1_scope_audit.json`
- `tests/test_phase2b_ds1_freeze_integration_r1.py` (real production control-path offline tests, with synthetic auth and network guard)

The design must include a **clear proof that the moving-main cycle no longer needs committing live grant artifacts after S**; enumerate operator action and immutable SHA identity. Distinguish `OFFLINE_INTEGRATION_PASS` from `LIVE_APPROVED`. Neither synthetically grant nor read `DEEPSEEK_API_KEY`.

## 4. Hard STOP conditions

Immediately stop, fail closed, and report exact stage:
- Any observed SHA, runtime, signer/trust anchor, signed intent, scope, ledger, run/token ID, expiry or artifact chain mismatch;
- fresh git remote proof absent/stale or worktree dirty, main/ref mismatched;
- external signed operator approval absent, revoked or still HOLD;
- credential callback invocation prior to independently valid grant and one-use reservation;
- any unexpected network call, redirect, response POST, canary, benchmark or retry (SDK/transport/operator);
- production gate bypass or tests that merely alter a local helper rather than exercising it;
- unexpected credential log/trace persistence, unsafe filesystem handles, audit/fsync/publish failure;
- full regression fails in the designated verified execution runtime; do not claim ready.
No external provider call or real credential read is authorized. `UNKNOWN` after uncertain attempt; stop with consumed reservation, never retry.

## 5. Acceptance and STOP

Report actual remote commit SHA, clean tree, exact changed files, synthetic production-path test counters, real Linux/Windows regression separately, hashes, risk/contract gaps, no real provider/key, and readiness `OFFLINE_INTEGRATION_READY_FOR_PLANNER_REVIEW` or `BLOCKED` / `FAILED`. Keep issue #18 open. **Do not approve, sign, provision live credentials, or execute GET /models.** Push only permitted new tests/docs/reports and STOP for Planner review.
