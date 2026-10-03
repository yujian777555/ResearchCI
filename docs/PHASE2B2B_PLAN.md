# Phase 2B-2B Plan — Single Synthetic Live Canary

Status: PLANNED

Precondition: Phase 2B-2A accepted/frozen at commit `fa20c9385701b22480a579d65b36e7ced21c2bee`.

Frozen execution protocol:

`sha256:8c21a5a702bdb3b494457fe54c47261df9fdc6e4629149ad84353717219a030c`

## Objective

Perform exactly **one synthetic, non-benchmark live OpenAI Responses episode** to verify that the frozen Phase 2B-2A-R2 execution path is accepted by the real provider end to end.

This phase is a transport/execution qualification only. It must not generate paper evidence and must not consume any ExpContractBench or Phase 2A benchmark scenario.

## Authorization boundary

Allowed external runtime network:
- only the OpenAI Responses request(s) required by this one canary episode.

Not allowed:
- model-list probes;
- capability probes unrelated to the canary;
- benchmark episodes;
- additional canary reruns;
- Phase 2C pilot;
- any protocol/schema/prompt/rule modification after the canary starts.

Git fetch/push used for development bookkeeping is outside runtime network accounting but must be reported separately.

## Credentials

Read the API credential only from the execution environment (for example `OPENAI_API_KEY`).

Never:
- print it;
- commit it;
- store it in trajectory artifacts;
- include it in request hashes before redaction.

If credentials are unavailable, STOP with status BLOCKED. Do not substitute another provider/model.

## Frozen live configuration

Use the already frozen Phase 2B-2A-R2 protocol without modification:

- provider: OpenAI
- endpoint: `/v1/responses`
- model: `gpt-5.6-sol`
- temperature: 0
- top_p: 1
- reasoning.effort: medium
- reasoning.context: all_turns
- store: true
- parallel_tool_calls: true
- continuation: `previous_response_id`
- max_steps: 30
- max_custom_function_calls: 20
- timeout_seconds: 900
- cumulative_output_token_budget: 16000
- retry policy: frozen Phase 2B retry policy.

Do not change any value to make the canary pass.

## Synthetic canary fixture

Create a dedicated temporary/non-benchmark workspace that is not under `agentbench/scenarios/**` or any formal benchmark manifest.

Synthetic file:

`CANARY.txt`

Exact content:

`RESEARCHCI_CANARY_OK_2B2B`

Agent-visible task:

> This is a transport qualification task. Use the available `read_file` tool exactly once to read `CANARY.txt`. Do not call any other tool. After receiving the tool result, return a concise final text containing the exact marker from the file.

This task must not mention:
- A0-A4;
- C001-C006;
- violation families;
- target stages;
- benchmark ground truth.

The same frozen system prompt and tool definitions remain in use.

## Synthetic mediator

The canary mediator must be minimal and deterministic:

- `read_file("CANARY.txt")` returns the exact marker;
- any other path is rejected;
- any other tool name is rejected;
- count mediator invocations;
- never execute benchmark code.

The mediator must not reveal evaluator-private metadata.

## Single-attempt rule

There is exactly **one canary episode**.

Do not rerun automatically if:
- the model does not call `read_file`;
- the model calls another tool;
- the request is rejected;
- provider/model behavior differs from expectation;
- the episode terminates incompletely.

A retry caused by the already-frozen provider retry policy is part of the same episode and must be recorded. It does not authorize a second episode.

If the canary fails, preserve the raw evidence and STOP for Planner review. Do not patch the protocol after seeing the live outcome.

## Required live evidence

Persist a redacted audit artifact containing at least:

- execution-protocol hash;
- episode ID;
- model requested;
- each provider response ID;
- each provider-returned model value;
- provider `created_at`;
- local UTC request/response timestamps;
- request kind (initial/continuation);
- `previous_response_id` for continuation;
- function-call `call_id` and function name;
- function arguments hash;
- mediator invocation count;
- usage.input_tokens;
- usage.output_tokens;
- usage.total_tokens;
- budget counters;
- provider/fake/live/network call counts;
- termination reason;
- final text hash and exact canary-marker presence;
- retry events, if any.

Do not store credentials or authorization headers.

## Success gates

The canary is PASS only if all of the following hold:

1. Real provider accepts the frozen initial request.
2. The model emits a `read_file` custom function call for `CANARY.txt`.
3. The custom call passes through the authoritative BudgetEnforcer/orchestrator path.
4. The mediator executes `read_file` exactly once.
5. No other mediator/tool execution occurs.
6. The continuation request uses the exact prior `response.id` as `previous_response_id`.
7. The `function_call_output.call_id` exactly matches the provider function-call `call_id`.
8. Real provider accepts the continuation request.
9. Final model output contains `RESEARCHCI_CANARY_OK_2B2B`.
10. Episode terminates `completed`.
11. `fake_provider_calls == 0`.
12. `live_api_calls == network_calls == provider_calls`, all greater than zero.
13. Provider response metadata and usage are present.
14. No runtime secret is present in saved artifacts.
15. Frozen protocol/hash, system prompt, tool schemas, scenarios, rules, and benchmark artifacts remain unchanged.

Any failed gate => canary FAIL, preserve evidence, STOP.

## Files/reports

Create canary-specific artifacts only, for example:

- `agentbench/live_canary/phase2b2b_canary.py`
- `agentbench/reports/phase2b2b_canary.json`
- `agentbench/reports/phase2b2b_regression.json`
- `agentbench/reports/phase2b2b_scope_audit.json`

The canary result must be explicitly labeled:

- synthetic;
- non-benchmark;
- excluded from Phase 2C metrics;
- excluded from paper efficacy claims.

## Regression and scope

After the live canary, run the full local regression suite.

The canary must not modify:

- `src/researchci/**`
- `src/researchci_agent/**`
- C001-C006
- `agentbench/scenarios/**`
- benchmark manifests
- system prompt
- tool schema
- provider contract
- agent config
- retry policy
- historical freeze reports.

If any frozen file changes after the first live request, mark the canary invalid and STOP.

## Completion report

Report:

- commit SHA;
- canary PASS/FAIL;
- number of canary episodes: exactly 1;
- provider/model/endpoint;
- provider_calls / live_api_calls / network_calls / fake_provider_calls;
- response IDs and returned model values;
- continuation previous_response_id match;
- call_id match;
- mediator invocation count;
- final marker present;
- token usage;
- retries;
- termination reason;
- full regression;
- protocol hash before/after;
- scope audit;
- credential leakage audit;
- deviations.

Then STOP.

Do not enter Phase 2C.
