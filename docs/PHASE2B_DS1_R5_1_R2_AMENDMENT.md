# Phase 2B-DS-1-R5.1-R2 — Evidence-path and LIVE_HTTP Safety Proof Completion

**Status: PLANNER REQUIRED / STRICTLY OFFLINE. R5.1-R1 IS NOT YET ACCEPTED FOR LIVE.**

Reviewed implementation `eb333420cf22b6e7f83b03fa9d28dab2efde0dbe` and report HEAD `7130db6114e2e69b9763267428e344eb406177f3`. Issue #18 stays OPEN.

## Verified progress

The R5.1-R1 changes added native handle-based evidence I/O, restricted path identity/reparse handling, an append lock, secure audit/summary operations, and enforced schema v2 public-key signatures for `LIVE_HTTP` ahead of credential callback and transport construction. Repository reports 426 passed, 2 skipped, 0 failed; these tests were **not independently rerun by Planner**.

R5.1-R1 fixed important vulnerabilities but the scope of security verification is incomplete. **Do not issue a real GET /models, read a real credential or issue POST /responses.**

## Blocker B1 — Windows skipped tests conceal multiple untested branches

The two symlink-creation tests skip on `WinError 1314`. In `tests/test_phase2b_ds1_r5_1_r1.py::test_audit_symlink_parent_and_preexisting_temp_fail_closed`, the test returns SKIP before the later pre-existing `summary.json.tmp` collision assertion when creating the first symlink fails. Therefore the report's blanket `preexisting_tmp: REJECT` is not proven by *that test* on the current Windows token.

**Required:**
1. Split symlink, junction/reparse, pre-existing predictable temp, hardlink, path traversal and summary collision cases into independent tests so missing symlink permission cannot skip unrelated protections.
2. On Windows, test link/reparse refusal through deterministic injected native-handle/file-attribute conditions where genuine link creation is not permitted; report this as simulated Windows-policy coverage, not a genuine on-disk symlink test.
3. Add a non-skippable symlink and junction-compatible on-disk security test lane on a platform/runner with the required privileges (Linux symlink test for symlinks; Windows privileged lane for junction/reparse where applicable). If such a lane cannot be run now, clearly mark `LINK_RUNTIME_VALIDATION_PENDING` and keep LIVE blocked.
4. Inject short write, fsync, permission failure, directory replacement, file replacement, concurrent append, crash/restart and verify no unintended external-file modification or accidental successful qualification.

## Blocker B2 — Atomic summary publish and protected read have unfinished paths

In `native_evidence.py::atomic_json` the existing-target branch refers to `PathIdentity(path)` but `PathIdentity` is **not imported** in that module. This currently raises `NameError` when the target exists, instead of a defined, audited single-use outcome. The function subsequently calls `os.replace(...)` on a path, bypassing the available pinned-directory no-overwrite publication helper `PinnedDirectory.publish(...)`.

Also `preflight.py::QualificationGate._persisted_evidence_valid` reads the persisted summary via plain `Path.read_text()`, instead of using the native secured read path.

**Required:**
1. Choose and document immutable once-per-run summary semantics. For the final preflight summary, an existing target must fail closed with a stable explicit error. Do **not** silently overwrite a historical or previously published outcome.
2. Implement native-handle/pinned-parent publication with exclusive unique temporary and non-overwrite semantics; preserve atomic visibility, fsync/read-back and cross-platform behavior. If the existing `PinnedDirectory.publish` helper is unsuitable, safely correct it within narrow R5.1-R2 scope.
3. Remove the undefined `PathIdentity` reference or import it intentionally if it is actually required; never rely on an accidental NameError as the overwrite guard.
4. Route *all* security-sensitive summary reads, including qualification read-back, through the secure native reader, with path identity and link/reparse checks.
5. Add explicit tests for existing summary target, predictable temp collision, target replacement during publish, symlink/reparse alias, and read identity replacement. A failure must not publish a PASS result or trigger a second network attempt.

## Blocker B3 — LIVE_HTTP schema v2 positive and denial ordering need execution proof

Existing `AuthorizationVerifier` public-key v2 validation is tested for `MOCK_HTTP`; legacy v1 `LIVE_HTTP` denial is tested. The authorized `LIVE_HTTP` **v2 positive path and full negative matrix ahead of credential access** remain insufficiently covered.

**Required fully offline:**
1. Generate a synthetic ephemeral v2 keypair **for testing only**, signed `LIVE_HTTP` intent, a synthetic expected harness SHA and temporary ledger.
2. Exercise the actual `execute_replacement_preflight` admission and `build_sdk_client` factory path under a **non-networking injected HTTPTransport substitute** / safe monkeypatch. No true socket, no environment credential lookup and no real provider access. The test should demonstrate one-use reservation, verified v2 identity, and that credential callback and transport construction occur only after all admission checks. Any attempt to create unmocked live HTTP must fail closed under a socket guard.
3. Test invalid key, mismatched key ID, expired/future issuance, revoked token/key, wrong run ID, token ID, stage, harness SHA, mode, ledger path, invalid signature, v1 LIVE authorization, dirty/wrong branch/stale remote, and reused token. Denied requests must show `credential_callback_count == 0`, `production_transport_construct_count == 0` and `external_provider_http_attempts == 0`.
4. Confirm PRECHECK_ONLY cannot invoke `POST /responses` even with otherwise-valid v2 approval.
5. The test must not ship any signing secret, public key/trust anchor or usable production authorization in the repo. Generated temporary test fixtures are acceptable.

## Frozen constraints

Accepted DeepSeek execution protocol:
`sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`.

Accepted statistics protocol:
`sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`.

Original `FAIL_PREFLIGHT_ARTIFACT` still has unknown first-request transport count, auth state and model presence. Preserve its committed evidence. No modifications to C001–C006/A0–A4, ResearchCI scientific core, Phase 2A scenarios/workspaces/manifests, accepted DeepSeek adapter/protocol, STATS code/protocol, system prompt/tool schema or historical reports.

Allowed: narrow `agentbench/deepseek_live_canary/**`, new/extended R5.1-R2 security tests, and new `agentbench/reports/phase2b_ds1_r5_1_r2_*.json` reports. Do not overwrite R5.1-R1 or older artifacts.

## Acceptance artifacts and STOP

Add:
- `phase2b_ds1_r5_1_r2_diagnostic.json`
- `phase2b_ds1_r5_1_r2_offline_e2e.json`
- `phase2b_ds1_r5_1_r2_regression.json`
- `phase2b_ds1_r5_1_r2_scope_audit.json`
- `phase2b_ds1_r5_1_r2_harness_freeze.json`
- `phase2b_ds1_r5_1_r2_security_review.md`.

Reports must explicitly distinguish `PASS`, `SKIPPED`, `SIMULATED`, `NOT_RUN` and any `LINK_RUNTIME_VALIDATION_PENDING` per test/platform. No blanket claim that skipped symlink tests passed.

Run full pytest; target 0 failed, state all skipped and reason. Freeze source and security hashes. Commit/push main, verify `HEAD == origin/main` and clean tree; STOP.

**Strictly offline: real provider API calls 0, real provider network 0, real credential reads 0, live canary 0, benchmark episodes 0. No human live authorization or production signed token is created.**
