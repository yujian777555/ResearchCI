# Phase 2B-DS-1 Plan — DeepSeek Credential/Model Preflight + Single Synthetic Live Canary

Status: **Planner-frozen for implementation/execution**

Depends on:
- DeepSeek DS-0-R1 accepted/frozen:
  `sha256:07cc0a68ec471f796dbc312c39f8386b6ff956d64524043adc11632c4bb448fe`
- Phase 2B-STATS-0-R1 accepted/frozen:
  `sha256:e6e262d95c55611f48541637a7ffbb8d75421632324030b52b0dd03477b5a083`

This phase is a **transport qualification stage only**. It is not a Phase-2 efficacy experiment and is excluded from CIER/EIFR/VTCR and all paper efficacy claims.

## 1. Objective

Qualify the frozen DeepSeek live path with:

1. exactly one non-generative credential/model-access preflight;
2. only if that preflight passes, exactly one synthetic non-benchmark live agent episode through the frozen DeepSeek Responses path.

No Phase 2A scenario or benchmark episode may be loaded.

## 2. Human credential gate

Before any live network call, the human operator must set:

`DEEPSEEK_API_KEY`

outside Git/repository files.

Rules:
- never print the key;
- never persist the key;
- never log Authorization/Bearer values;
- never include the key in prompts, reports, traces, exception text, Git history, shell history intentionally, or screenshots.

If the key is not present, STOP before network access.

## 3. Strong sequencing / pre-live harness freeze

Before the first network call:

1. implement the DS-1 preflight + canary harness offline;
2. add deterministic tests;
3. run full regression offline;
4. create pre-live audit/scope reports;
5. commit and push the harness;
6. record the exact `CANARY_HARNESS_COMMIT`;
7. require `HEAD == origin/main` and a clean worktree.

Only after that frozen harness commit may the credential preflight run.

After the first live network call:
- do not modify provider protocol, replay logic, retry logic, tool schema, prompt, budgets, canary fixture, canary task, or mediator in order to improve the result;
- only sanitized result/audit/bookkeeping artifacts may be added.

## 4. Gate A — exactly one non-generative model-access preflight

Perform exactly one HTTP-equivalent request:

`GET https://api.deepseek.com/models`

The implementation may use the OpenAI-compatible SDK `client.models.list()` if and only if it produces that single model-list request.

This preflight:
- is not an agent episode;
- must not call `/responses`;
- must not generate model output;
- must not load benchmark scenarios.

Pass condition:
- authentication succeeds;
- HTTP/provider operation succeeds;
- returned model list contains exact model id `deepseek-v4-pro`.

Record only sanitized target-model evidence:
- PASS/FAIL;
- local UTC request/response timestamps;
- target model id requested/checked;
- whether target was present;
- target model metadata if returned (e.g. context/output/effort capability fields);
- provider request id/header identifier if safely available;
- sanitized error type/status if failed.

Do not persist the API key or Authorization header.

### Preflight failure rule

If preflight fails or `deepseek-v4-pro` is absent:
- replacement canary episodes = 0;
- write sanitized preflight/audit result;
- commit/push result artifacts;
- STOP for Planner review.

Do not call `/responses`.

## 5. Synthetic canary fixture

Only if Gate A passes, execute exactly one synthetic canary.

Create an independent canary workspace that does not import/materialize Phase 2A benchmark scenarios.

Fixture:

`CANARY.txt`

Exact file content:

`RESEARCHCI_DEEPSEEK_CANARY_OK_DS1`

Agent-visible task:

> This is a transport qualification task. Use the available `read_file` tool exactly once to read `CANARY.txt`. Do not call any other tool. After receiving the tool result, return a concise final text containing the exact marker from the file.

Use the frozen ResearchCI system prompt semantic content and frozen tool schema. Do not add hidden instructions that reveal benchmark rules/conditions.

## 6. Synthetic mediator

The canary mediator must:
- allow only `read_file`;
- allow only path exactly `CANARY.txt`;
- return the exact marker;
- reject any other tool/path;
- count mediator invocations;
- never touch Phase 2A admission/evaluator state.

The mediator is synthetic transport qualification infrastructure, not benchmark evidence.

## 7. Authoritative live path

The canary must run through:

```
DS-1 canary runner
  -> EpisodeOrchestrator
  -> DeepSeekRequestBuilder
  -> DeepSeekResponsesAdapter
  -> real DeepSeek /responses
  -> provider function_call
  -> local replay projection / validation
  -> BudgetEnforcer
  -> synthetic mediator
  -> function_call_output
  -> stateless full-history replay
  -> real DeepSeek /responses
  -> final assistant message
```

Do not bypass the authoritative orchestrator/budget/replay path.

## 8. Frozen DeepSeek request semantics

Do not change:
- base URL: `https://api.deepseek.com`
- endpoint: `/responses`
- model: `deepseek-v4-pro`
- reasoning effort: `max`
- top_p: `0.95`
- temperature: omitted
- provider seed: not sent
- tool_choice: `auto`
- stateless full-history replay
- no `previous_response_id`
- no `conversation`
- no `store`
- no `metadata`
- no `parallel_tool_calls` request field
- local tool schema validation
- replay response->input projection
- executable DeepSeek error normalization.

## 9. Frozen budgets / retry

Keep:
- max_steps = 30
- max_custom_function_calls = 20
- timeout_seconds = 900
- cumulative_output_token_budget = 16000
- dynamic max_output_tokens from remaining budget
- frozen bounded retry semantics.

Within the **single canary episode**, provider retries allowed by the already-frozen retry policy do not count as a second canary episode.

Do not restart the canary after terminal success/failure.

## 10. Single-attempt rule

Exactly one synthetic canary episode is authorized after a successful preflight.

If the canary:
- fails provider-side;
- violates the requested one-tool behavior;
- calls another tool;
- calls `read_file` more than once;
- fails replay;
- times out;
- ends incomplete;
- omits the marker;

preserve the outcome and STOP.

No second/third canary is authorized by this phase.

## 11. Canary success gates

PASS requires all:

1. Gate A preflight PASS and target `deepseek-v4-pro` present.
2. Exactly one canary episode.
3. Initial `/responses` request accepted.
4. Requested model = `deepseek-v4-pro`.
5. Returned model identifier recorded.
6. Provider emits exactly one function call.
7. Function name exactly `read_file`.
8. Arguments resolve exactly to `{"path":"CANARY.txt"}` after the frozen local validation path.
9. Provider `call_id` is non-empty and is preserved exactly into `function_call_output`.
10. Mediator invocation count = 1.
11. No other tool is invoked.
12. Stateless replay includes the initial user task, projected prior provider items, and matching function output.
13. Replay contains no forbidden response-only fields.
14. Continuation `/responses` request is accepted.
15. Final assistant output contains exact marker `RESEARCHCI_DEEPSEEK_CANARY_OK_DS1`.
16. Termination = `completed`.
17. fake_provider_calls = 0.
18. live/network/provider call accounting is internally consistent.
19. No benchmark/scenario episode loaded.
20. No credential leakage.
21. DeepSeek protocol hash remains the accepted DS-0-R1 hash.
22. Statistical protocol hash remains the accepted STATS-0-R1 hash.
23. Full regression remains green.

## 12. Provider metadata / audit

Record sanitized live metadata when available:
- provider/model requested;
- returned model id;
- response ids;
- response created_at/provider timestamps;
- local UTC request/response timestamps;
- output item types;
- input/output/total token usage;
- cached input tokens if returned;
- reasoning tokens if returned;
- retry indexes/backoff;
- tool call id/name/argument hash;
- replay/request hashes;
- termination reason;
- accounting counters.

Never persist secrets.

## 13. Preflight/canary classifications

Preflight:
- `PASS`
- `FAIL_AUTH`
- `FAIL_BALANCE`
- `FAIL_TARGET_MODEL_ABSENT`
- `FAIL_PROVIDER`
- `FAIL_NETWORK`
- another stable sanitized infrastructure class if necessary.

Canary:
- `PASS`
- `FAIL_PROVIDER`
- `FAIL_MODEL_BEHAVIOR`
- `FAIL_TOOL_PROTOCOL`
- `FAIL_REPLAY`
- `FAIL_TIMEOUT`
- `FAIL_INCOMPLETE`

This is transport qualification. Do not map these outcomes to CIER/EIFR/VTCR.

## 14. Required artifacts

Before live request, create/freeze harness code/tests plus a pre-live report.

After outcome, add result-only artifacts such as:

- `agentbench/reports/phase2b_ds1_preflight.json`
- `agentbench/reports/phase2b_ds1_canary.json` (or NOT_RUN record if preflight fails)
- `agentbench/reports/phase2b_ds1_live_audit.json`
- `agentbench/reports/phase2b_ds1_regression.json`
- `agentbench/reports/phase2b_ds1_scope_audit.json`

Record:
- Planner spec commit;
- canary harness commit;
- final result commit;
- DeepSeek DS-0-R1 protocol hash;
- STATS-0-R1 protocol hash.

Do not overwrite older OpenAI or DeepSeek offline reports.

## 15. Pre-live tests

Before the credential preflight, add offline tests proving:
- the canary fixture/task are exact;
- synthetic mediator only allows one exact read;
- runner uses the existing DeepSeek adapter/orchestrator;
- no benchmark scenario is imported/materialized;
- live transport is injectable;
- credential is not logged;
- target preflight parser selects only `deepseek-v4-pro`;
- preflight failure prevents canary;
- exactly one canary episode gate exists;
- no automatic rerun;
- result serializer redacts secret-like strings;
- full historical regression remains green.

These tests must not access network.

## 16. Scope

Do not modify:
- `src/researchci/**`
- `src/researchci_agent/**`
- C001-C006
- A0-A4 semantics
- Phase 2A scenarios/workspaces/manifests
- DeepSeek DS-0-R1 provider protocol semantics
- STATS-0-R1 statistical semantics
- historical OpenAI provider/canary evidence
- system prompt semantic content
- tool schema semantic content.

A narrow DS-1 live harness/credential client construction layer is allowed.

## 17. Result commit discipline

Pre-live:
- harness commit must be pushed before Gate A.

Post-live:
- do not edit execution/protocol code;
- add sanitized result/audit/regression/scope artifacts only, unless a purely non-execution bookkeeping file is required;
- commit/push;
- require clean synchronized main.

Git history demonstrates repository chronology; it does not prove the absence of unrecorded local execution. Do not overclaim beyond auditable repository evidence.

## 18. STOP rule

After:
- a failed Gate A preflight, OR
- the single canary PASS/FAIL,

STOP.

Do not run:
- another canary;
- Phase 2 pilot;
- formal benchmark;
- any Phase 2A live scenario.

Planner review is mandatory before Phase 2C pilot authorization.
