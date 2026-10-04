# Phase 2B-2B-R1 Plan — Credential Recovery + One Replacement Canary

Status: PLANNED / BLOCKED ON HUMAN CREDENTIAL REMEDIATION

Parent live attempt:
- harness commit: `910b4df191739cd986349407a745a7b2d895db29`
- failed result commit: `2cc2c4659e6335a2e9d32c847a5980faa5a442c2`
- failure: `AuthenticationError` before any provider response
- frozen execution protocol: `sha256:8c21a5a702bdb3b494457fe54c47261df9fdc6e4629149ad84353717219a030c`

## Scientific interpretation

The first canary is permanently retained as an infrastructure-invalid attempt. Authentication failed before the provider accepted the model request, so there was no model output, function call, mediator execution, continuation, token usage, or benchmark evidence.

A single replacement canary is methodologically allowed only because:
1. the original live outcome contained no model behavior;
2. the frozen research protocol remains unchanged;
3. credential remediation is external infrastructure repair;
4. the failed attempt remains preserved and reported;
5. the replacement protocol is preregistered before any second model-generating request.

## Phase boundary

This phase has two sequential gates.

### Gate A — human credential remediation

No repository/protocol change is authorized.

The human operator must repair the execution environment outside Git:
- verify/create a valid OpenAI API key;
- ensure the key belongs to the intended API project/organization;
- ensure the key is active and permitted from the execution environment;
- update `OPENAI_API_KEY` in the process environment;
- do not expose the secret to logs, commits, prompts, screenshots, or reports.

If the environment uses explicit organization/project routing, those values may be supplied through environment configuration, but must not modify the frozen ResearchCI protocol.

### Gate B — one credential/model-access preflight

After human remediation, authorize exactly one non-generative API preflight:

`GET /v1/models/gpt-5.6-sol`

Purpose:
- verify API authentication;
- verify that the intended key/project can retrieve the frozen model identity.

This is infrastructure qualification, not a canary episode and not benchmark evidence.

Record only:
- HTTP/API success or sanitized failure type/code;
- returned model id if successful;
- local UTC timestamps;
- request ID if exposed by the SDK/API;
- zero secrets.

Do not list all models. Do not call Responses. Do not invoke any model generation in the preflight.

If the preflight fails:
- preserve sanitized evidence;
- run zero replacement canary episodes;
- STOP for Planner review.

If the preflight succeeds:
- proceed immediately to the single replacement canary with no protocol/code/schema/prompt changes.

## One replacement canary

Exactly one replacement synthetic canary episode is authorized after a successful Gate B.

Reuse unchanged:
- the previously frozen canary harness behavior;
- `CANARY.txt = RESEARCHCI_CANARY_OK_2B2B`;
- agent-visible canary task;
- synthetic mediator;
- frozen system prompt;
- frozen tool schema;
- frozen provider request contract;
- frozen budgets/retry policy;
- model `gpt-5.6-sol`;
- Phase 2B-2A-R2 execution protocol hash.

Do not alter the canary to improve success probability.

## Replacement success gates

Identical to Phase 2B-2B:
- provider accepts initial Responses request;
- exactly one `read_file(CANARY.txt)` mediator execution;
- exact call_id preservation;
- exact previous_response_id preservation;
- provider accepts continuation;
- final marker present;
- termination `completed`;
- fake_provider_calls=0;
- live/network/provider accounting consistent;
- no benchmark scenario loaded;
- no credential leakage;
- protocol hash unchanged;
- full regression green.

## Failure rule

Any failure after the replacement canary starts is preserved as evidence.

No third canary is authorized.

No protocol repair after seeing the replacement live outcome.

## Reporting

Create R1-specific artifacts that retain links/hashes to both:
- original authentication-failed attempt;
- credential/model-access preflight;
- replacement canary if and only if preflight passes.

Clearly label:
- original attempt: `INVALID_INFRA_AUTH`;
- preflight: `PASS` or `FAIL`;
- replacement canary: `PASS`, `FAIL`, or `NOT_RUN`.

All are excluded from Phase 2C metrics and paper efficacy claims.

## Scope

No modifications to:
- `src/researchci/**`
- `src/researchci_agent/**`
- C001-C006
- `agentbench/scenarios/**`
- `agentbench/workspaces/**`
- system prompt
- tool schema
- provider contract
- agent config
- retry policy
- historical freeze reports
- previously committed failed canary artifacts.

Only R1 credential-preflight/replacement-canary runner/report bookkeeping may be added if needed, and it must reuse the frozen execution path.

## Stop

After Gate B failure, or after the single replacement canary, STOP.

Phase 2C remains blocked until Planner review.
