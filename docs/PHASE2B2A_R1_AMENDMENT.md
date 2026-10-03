# Phase 2B-2A-R1 Amendment

Status: Planner repair required before Phase 2B-2A acceptance.

Reviewed commit: `90964fc9c1658f2837fa629514de0ef0f5fd80c5`.

The offline adapter/orchestrator structure is directionally correct, but four execution-contract defects must be fixed before any live canary.

## 1. Preserve Responses conversation state across function calls

The current orchestrator replaces the next request input with only `function_call_output` items. That is not a sufficient state-preserving continuation contract.

Use one documented Responses pattern consistently:

- stateful: send `previous_response_id=<last response id>` plus the new `function_call_output` items; or
- stateless: replay the required prior response output items, including function-call/reasoning items, before the corresponding `function_call_output` items.

Freeze the chosen mode in the provider request contract and test the exact request shape.

Do not run a live request in this phase.

## 2. Make function schemas executable for nested research objects

The current request builder emits nested object fields such as `baseline_intent`, `candidate_intent`, `current_run`, `cached_artifact`, `run_result`, and `aggregate` as empty strict objects with `additionalProperties:false`.

That schema cannot carry the actual fields required by the Phase 2A mediator.

Replace these placeholders with explicit strict JSON Schemas matching the real mediator payload contracts. Add offline tests for every tool type, especially:

- run_experiment
- consume_cache
- record_run_result
- propose_aggregate
- finish_episode

Tests must prove representative valid payloads survive schema validation and reach the mediator unchanged, while malformed payloads are rejected.

## 3. Make retry behavior match the frozen retry policy

`retry_policy.json` declares bounded exponential backoff, but the orchestrator currently calls `sleep(0)` and does not re-check the episode timeout before each retry.

Required:

- compute backoff from the frozen policy;
- inject sleep for tests;
- re-check the monotonic episode timeout before every retry;
- record retry delay and local request-attempt timestamps;
- do not reset step/tool/token budgets;
- no tool replay after successful execution.

Add deterministic fake-clock tests.

## 4. Correct provider-call accounting

`TrajectoryResult.live_api_calls` is currently populated from `adapter.calls`, so fake-provider calls are counted as live API calls inside the result even though Phase 2B-2A reports correctly claim zero live calls.

Separate at least:

- provider_calls
- fake_provider_calls
- live_api_calls
- network_calls

For the offline fake-provider E2E, `live_api_calls` and `network_calls` must both be exactly zero in the returned trajectory/result as well as in the aggregate reports.

## 5. Required regression tests

Add tests proving:

1. function-call continuation preserves prior Responses state using the frozen mode;
2. nested strict schemas can express valid Phase 2A mediator payloads for all tool types;
3. retry backoff and timeout are both enforced across retries;
4. offline fake-provider trajectories report zero live API calls and zero network calls;
5. no hidden evaluator metadata leaks into agent-visible input;
6. full regression remains green;
7. benchmark episodes remain zero.

Regenerate the adapter-source, runner-source, provider-contract (if changed), trajectory schema (if changed), and Phase 2B-2A execution-protocol hashes.

Then STOP. Do not enter Phase 2B-2B.
