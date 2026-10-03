# Phase 2B-2A-R2 Amendment — Provider-Strict Schema + Request-Parity + Timeout Semantics

Status: **Planner-required final offline repair before Phase 2B-2A acceptance**

Reviewed remote HEAD:
`c99b4329ae1f7989ca85653e9d26abc010134540`

R1 correctly fixed response chaining, retry execution, accounting separation, and the empty-object tool schemas. Three live-blocking protocol defects remain.

## 1. Tool schemas must be valid for OpenAI strict function calling, not only for the local validator

The current tool definitions are emitted with `strict: true`.

For OpenAI strict function calling, every object must have `additionalProperties: false` and every field in `properties` must be included in that object's `required` list. Optional values must be represented with a strict-compatible schema (for example nullable fields or strict-compatible variants), rather than simply omitting them from `required`.

The current `agentbench/tool_schema.json` violates this constraint recursively. Examples include:

- `run_experiment`: `baseline_intents` / `candidate_intents` are properties but are not required;
- nested `resolved_config` objects have properties with `required: []`;
- `consume_cache.cached_artifact.source_provenance` has declared properties not marked required;
- `record_run_result.run_result` has optional declared properties;
- `propose_aggregate.aggregate` and nested objects have declared properties not marked required.

A real Responses request with these tools can therefore be rejected before the agent ever runs.

### Required repair

- Keep `strict: true` unless Planner explicitly approves a protocol change.
- Make every emitted function schema satisfy the provider strict-mode constraints recursively.
- Preserve the semantic payload expected by the existing Phase 2A mediator. Do not add semantic fields to the mediator payload merely to satisfy the schema.
- If optional/domain-variable fields require unions/nullable fields/strict-compatible variants, implement that explicitly.
- If strict compatibility cannot be achieved without changing the mediator payload semantics, STOP and report instead of silently setting `strict:false`.
- Add a recursive static provider-compatibility validator and tests that fail if any object has:
  - `additionalProperties != false`, or
  - `set(properties) != set(required)`.
- Run this validator over every tool emitted to Responses.

Representative Phase 2A payload tests must still pass unchanged.

## 2. Freeze identical generation configuration on initial and continuation requests

The current initial request sends:

- `temperature: 0`
- `top_p: 1`

but the continuation request omits them.

`previous_response_id` preserves conversation state; it does not justify silently changing request-level generation configuration. The study must not use one sampling configuration on the first model cycle and provider defaults on later cycles.

Before live execution, freeze and send the same generation configuration on every model request.

Required protocol fields:

- model: `gpt-5.6-sol`
- temperature: `0`
- top_p: `1`
- reasoning effort: explicitly freeze `medium`
- reasoning context: explicitly freeze `all_turns`
- `store: true` because this study uses server-side `previous_response_id` continuation
- `parallel_tool_calls: true` (preserves the already-tested multi-call behavior)
- dynamic `max_output_tokens` from the remaining runner budget
- stable instructions and tool definitions on every request where required by the frozen continuation contract.

Update `agent_config.yaml` / provider request contract as needed so these are explicit protocol choices rather than provider defaults.

Add tests proving initial and continuation requests have identical frozen model/sampling/reasoning/state/tool-parallelism settings, except for fields that must differ by turn (`input`, `previous_response_id`, dynamic token cap, metadata as applicable).

No live API call is allowed.

## 3. Timeout must remain authoritative after provider latency and during tool dispatch

The current orchestrator re-checks timeout around retries, but a successful provider call can return after the 900-second episode deadline.

Required:

- immediately after every provider response returns, re-check the monotonic episode timeout before any function call is dispatched;
- before each custom function dispatch, preserve the same timeout authority;
- if `BudgetEnforcer.execute_custom_function()` denies execution because the timeout expired, terminate as `timeout_exhausted`, not `tool_budget_exhausted`;
- preserve `tool_budget_exhausted` only when the custom-function count is actually exhausted.

Add deterministic fake-clock tests for:
1. provider call begins before deadline and returns after deadline -> no mediator/tool execution, termination `timeout_exhausted`;
2. timeout occurs between multiple tool calls -> remaining calls do not reach mediator, termination `timeout_exhausted`;
3. 21st tool call with time still available -> termination `tool_budget_exhausted`.

## 4. Freeze/report versioning

Do not rewrite Phase 2B-1 or earlier Phase 2B-2A historical freeze records.

Create R2-specific reports and a new execution-protocol hash, with parent:

`sha256:e80d439b9ee25d58813009fdf59f13e519ce61a32ece29a80cec66bfe42b58ba`

Regenerate at least:

- tool-schema hash;
- provider-request-contract hash;
- agent-config hash if changed;
- runner-source hash;
- adapter-source hash if changed;
- trajectory-schema hash if changed;
- Phase 2B-2A-R2 execution-protocol hash.

Reports must continue to state:

- live/API calls: 0
- network calls: 0
- formal benchmark episodes: 0

## 5. Scope

Do not modify:

- `src/researchci/**`
- `src/researchci_agent/**`
- C001-C006
- Phase 1 artifacts
- scenario semantic content
- frozen system prompt

Run the full regression suite and the new R2 offline tests.

Then STOP.

No synthetic live canary and no Phase 2C until Planner accepts this R2.
