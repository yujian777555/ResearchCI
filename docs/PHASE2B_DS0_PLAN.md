# Phase 2B-DS-0 Plan — DeepSeek Provider Adaptation (Offline Freeze)

Status: PLANNED

## Why this phase exists

The previously frozen OpenAI live protocol remains historically valid, but the first OpenAI canary ended before model execution with `AuthenticationError`. The project is now intentionally adding a **separate DeepSeek provider track** rather than pretending a DeepSeek key/model is interchangeable with the frozen OpenAI protocol.

Historical OpenAI evidence must remain unchanged:
- OpenAI offline protocol: Phase 2B-2A-R2
- OpenAI canary result: infrastructure-invalid authentication failure
- no OpenAI model behavior was observed

This phase is provider adaptation only. It must not run a live DeepSeek request.

## Provider choice

Freeze DeepSeek as the primary live backend for the next qualification track:

- provider: DeepSeek
- OpenAI-compatible base URL: `https://api.deepseek.com`
- API family: Responses API
- endpoint: `/responses`
- model: `deepseek-v4-pro`
- reasoning effort: `max`
- top_p: `0.95`
- temperature: **omit** (thinking mode ignores it)
- provider seed: not used
- max output tokens: runner-controlled from remaining cumulative output budget
- tools: function tools
- tool choice: `auto`

Rationale: DeepSeek documents `deepseek-v4-pro` as the stronger agent-oriented model and recommends max effort for highly complex agent tasks. This benchmark is intended to test runtime enforcement against a capable agent, not to optimize model cost.

## Critical compatibility differences from the OpenAI track

DeepSeek Responses is **stateless**.

Therefore the DeepSeek track MUST NOT rely on:
- `previous_response_id`
- server-side conversation state
- `store=true`
- OpenAI-style metadata persistence
- OpenAI `reasoning.context=all_turns`

DeepSeek documentation states:
- `previous_response_id` unsupported;
- `conversation` unsupported;
- `store` unsupported and responses report `store:false`;
- `metadata` unsupported;
- `parallel_tool_calls` is ignored because parallel tool calling is always enabled;
- full conversation history must be sent in `input` for every turn.

Do not send unsupported fields merely because the server silently ignores them.

## Stateless replay contract

Implement one canonical DeepSeek conversation-history representation.

Initial request:
- frozen instructions/system prompt;
- agent-visible task represented as a user/message input item;
- function tools;
- reasoning effort=max;
- top_p=0.95;
- dynamic max_output_tokens.

After each provider response:
1. retain the full prior input history;
2. append all provider output items required to preserve context, including supported `reasoning`, `message`, and `function_call` items;
3. execute custom functions only through the existing authoritative BudgetEnforcer/orchestrator path;
4. append matching `function_call_output` items with exact provider `call_id`;
5. send the complete replay history as the next request `input`.

Do not fabricate or rewrite provider reasoning/function-call items. Preserve ordering.

## Tool schema policy

Do NOT use DeepSeek beta strict mode in this track.

- use the stable `https://api.deepseek.com` base URL;
- function tools remain schema-described;
- omit provider `strict:true`;
- retain ResearchCI's local recursive schema validation before mediator dispatch;
- malformed/unknown tool arguments must still be rejected before mediator execution.

This avoids silently changing to DeepSeek's beta endpoint solely for provider-side strict validation while preserving the actual ResearchCI enforcement boundary.

## Architecture

Create provider-specific adapter/protocol files rather than overwriting the historical OpenAI freeze.

Preferred structure:

- `agentbench/deepseek_adapter/**`
- `agentbench/deepseek_protocol/**`
- narrow shared-runner changes only when provider-neutral and regression-safe
- DeepSeek-specific reports/tests

Do not mutate historical OpenAI freeze reports.

The DeepSeek adapter may use the OpenAI Python SDK with:

- `api_key=os.environ["DEEPSEEK_API_KEY"]`
- `base_url="https://api.deepseek.com"`

No credential may be committed or logged.

## Existing ResearchCI semantics that remain frozen

Do not change:
- C001-C006;
- A0-A4 condition semantics;
- Phase 1 benchmark;
- Phase 2A scenarios/workspaces;
- evaluator/metrics;
- system prompt semantic content;
- runner budgets:
  - max_steps=30
  - max_custom_function_calls=20
  - timeout_seconds=900
  - cumulative_output_token_budget=16000
- retry semantics unless DeepSeek transport error mapping requires a provider-specific classification layer; any such mapping must preserve the same retryable/non-retryable meaning.

## Offline fake-provider requirements

Build a deterministic DeepSeek fake provider that uses the **same stateless replay orchestration path** as future live execution.

Minimum offline E2E:

1. text-only completion;
2. one function call + stateless replay continuation;
3. multiple parallel function calls + outputs;
4. full-history replay contains initial user task;
5. replay contains prior provider reasoning item(s) when emitted;
6. replay contains provider function_call item(s);
7. exact call_id preserved into function_call_output;
8. no previous_response_id anywhere;
9. no store/metadata/conversation fields;
10. reasoning effort=max on every provider request;
11. top_p=0.95 on every provider request;
12. temperature absent;
13. provider-supported request field allowlist enforced;
14. local tool-argument validation still blocks malformed payload before mediator;
15. existing step/tool/timeout/cumulative-output budget semantics preserved;
16. fake/live/network accounting separated;
17. no evaluator-private metadata in agent-visible history;
18. zero external network calls.

## Provider response parsing

Capture at minimum:
- response id, if returned;
- returned model identifier;
- created_at if returned;
- response output item types;
- usage input/output/total tokens;
- input cached tokens if available;
- reasoning token count if available;
- local UTC request/response timestamps.

Response IDs are audit metadata only. They are NOT conversation-state handles in the DeepSeek track.

## DeepSeek execution protocol freeze

Create a new provider-specific execution-protocol hash independent of the historical OpenAI hash.

The DeepSeek composite must cover at least:
- provider config;
- request contract;
- stateless replay contract/schema;
- system prompt hash;
- tool schema hash;
- scenario semantic hash;
- environment hash;
- runner source hash;
- DeepSeek adapter source hash;
- retry policy/mapping hash.

Record the OpenAI R2 hash only as historical lineage/reference, not as the DeepSeek parent semantics.

## Scope and no-live rule

Strictly forbidden in DS-0:
- any DeepSeek API request;
- any external runtime network;
- any OpenAI API request;
- any live canary;
- any benchmark episode;
- Phase 2C.

Full regression must remain green.

## Acceptance gates

DS-0 may be accepted only if:
- deterministic fake-provider E2E passes;
- stateless replay is exact and replayable;
- no unsupported stateful OpenAI fields are sent;
- all function calls still pass through the authoritative BudgetEnforcer/mediator path;
- local argument validation remains enforced;
- budget/timeout/accounting semantics remain unchanged;
- leakage audit passes;
- scope audit passes;
- new DeepSeek execution-protocol hash is reproducible;
- live/API/network calls = 0;
- benchmark episodes = 0.

Then STOP.

## Next phase (not yet authorized)

Phase 2B-DS-1:
1. human sets `DEEPSEEK_API_KEY` outside Git;
2. one non-generative `GET /models` preflight verifies authentication and that `deepseek-v4-pro` is available;
3. only if preflight passes, exactly one synthetic non-benchmark DeepSeek live canary;
4. Planner review before any Phase 2C pilot.
