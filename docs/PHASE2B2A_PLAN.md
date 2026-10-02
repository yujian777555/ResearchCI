# Phase 2B-2A Plan — OpenAI Live Adapter Integration (Offline Freeze)

Status: PLANNED
Precondition: Phase 2B-1 accepted/frozen at `21c63905a6f85cc7b907377c736abd7a00a79d85`.

## Objective

Implement the real OpenAI Responses adapter and episode orchestration path that will later be used for live evaluation, while keeping this phase strictly offline.

No OpenAI request, live-agent episode, or benchmark result may be produced in Phase 2B-2A.

## Research validity goal

Before the first provider call, prove locally that the execution path preserves the frozen Phase 2B protocol:

- identical agent-visible prompt/context across A0-A4 except for mediator behavior already defined by the benchmark;
- every model decision cycle passes through the runner step/timeout/output-token budget;
- every custom function call passes through the runner custom-function budget before reaching the mediator;
- every provider response usage record updates the cumulative output-token budget;
- provider metadata and local timestamps are captured without exposing hidden evaluator metadata to the agent;
- raw trajectories are append-only and replayable.

## Scope

Allowed:
- `agentbench/live_adapter/**` (preferred)
- narrowly required changes to `agentbench/live_runner/**`
- Phase 2B-2A tests/reports
- protocol/version metadata needed to freeze the adapter-integrated execution path.

Forbidden:
- `src/researchci/**`
- C001-C006 rule changes
- Phase 1 benchmark/reports
- scenario semantic changes
- system prompt changes
- A0-A4 protocol changes
- live API calls
- benchmark episodes.

## Adapter contract

Implement an OpenAI Responses adapter for model `gpt-5.6-sol` and endpoint `/v1/responses`.

The adapter must:

1. build requests exclusively from the frozen provider request contract;
2. never send provider `seed`;
3. never use provider `max_tool_calls` as the ResearchCI custom-function budget;
4. set each request's `max_output_tokens` from the current runner-side remaining output-token budget;
5. parse text and custom function-call outputs;
6. send function results back using the documented function-call continuation shape;
7. record response ID, model alias returned by provider, provider `created_at`, local UTC request/response timestamps, and usage fields;
8. never expose provider credentials in logs or artifacts.

## Episode orchestration contract

Create a single authoritative orchestration loop.

Required order:

1. load the blinded episode context;
2. check timeout/step budget before each model cycle;
3. compute remaining output-token budget;
4. build provider request;
5. obtain adapter response (fake adapter only in this phase);
6. record provider metadata/usage;
7. update cumulative output-token budget;
8. for each custom function call:
   - check/enforce custom-function budget;
   - only then dispatch to mediator/tool;
   - record call, outcome, and any block/repair information;
9. append trajectory event(s);
10. continue or terminate with an explicit reason.

There must not be a second execution path that bypasses these checks.

## Offline fake-provider test matrix

Use a deterministic fake Responses adapter. Cover at least:

- text-only completion;
- one function call followed by function-call output continuation;
- multiple function calls;
- 20 allowed custom function calls and blocked 21st;
- step budget exhaustion;
- cumulative output-token exhaustion;
- monotonic timeout;
- provider error/retry surface;
- malformed function arguments;
- tool/mediator rejection;
- incomplete episode;
- explicit successful completion;
- identical runtime budget behavior across A0-A4.

No test may contact the network.

## Retry policy freeze

Define retryable vs non-retryable provider failures before any live call.

The retry policy must:
- use a bounded retry count;
- not reset episode budgets;
- record every retry and error;
- preserve provider request/response metadata;
- not silently repeat tool execution.

Do not invent provider-specific retry behavior without documenting it in the adapter contract.

## Trajectory/audit artifact

Define an append-only episode trajectory schema including at least:

- episode ID (opaque)
- replicate ID
- condition only in evaluator-side metadata, never agent-visible context
- step index
- request metadata hash
- provider response metadata
- token usage
- model output item types
- function-call IDs/names/argument hashes
- mediator/tool outcome
- budget counters
- termination reason
- protocol/composite hash.

Secrets and raw API keys must never be stored.

## Freeze/versioning

Phase 2B-1 remains an immutable historical freeze record.

Because adapter integration changes executable runner code, Phase 2B-2A must create a **new** authoritative execution-protocol version and composite hash. Do not rewrite history to pretend the Phase 2B-1 composite hash still describes the new source tree.

Record:
- parent Phase 2B-1 composite hash;
- new adapter-source hash;
- new runner-source hash;
- new execution-protocol composite hash;
- provider-contract hash;
- scenario/tool-schema/prompt/config hashes.

## Acceptance gates

All must pass:

- full regression green;
- zero network/live calls;
- zero benchmark episodes;
- fake-provider end-to-end orchestration tests green;
- no budget-bypass path;
- leakage audit green;
- scope audit green;
- new execution-protocol hash reproducible;
- raw trajectory schema validated;
- retry semantics frozen.

Then STOP.

Do not proceed to live smoke or Phase 2C.

## Next phase (not authorized here)

Phase 2B-2B will perform a single **synthetic non-benchmark live canary** only after Planner accepts Phase 2B-2A.
