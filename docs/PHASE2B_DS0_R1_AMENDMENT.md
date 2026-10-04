# Phase 2B-DS-0-R1 Amendment — Input-Safe Replay + Executable Provider Error Mapping

Status: **Planner-required final offline repair before DeepSeek DS-0 acceptance**

Reviewed implementation commit:
`6cd8473764473076e006ce26e134debe082e5ca7`

The DS-0 architecture is directionally correct and scope-clean. The stateless replay path, provider-specific separation, local tool validation, budget enforcement, accounting, and no-live discipline are all substantially in place. Two live-blocking gaps remain.

## 1. Replay must project provider OUTPUT items into DeepSeek-supported INPUT items

Current behavior in `DeepSeekRequestBuilder.extend_history()` appends provider `response.output` dictionaries verbatim into the next request input.

That is unsafe for a real DeepSeek Responses call because response output items contain response-only fields such as:
- `id`;
- `status`;
- reasoning `summary`;
- message-content annotations and other output-only metadata.

DeepSeek documents the accepted stateless input representation separately:
- `message` input: role + supported content;
- `reasoning` input: plain-text `content` containing `reasoning_text` parts;
- `function_call` input: `call_id`, `name`, `arguments`;
- `function_call_output`: `call_id` + output.

DeepSeek also explicitly documents that reasoning `summary` / `encrypted_content` are not supported as replay input.

### Required repair

Add one canonical, deterministic **provider-output -> provider-input replay projection**.

For every provider output item used in future history:

- `reasoning` -> preserve the exact ordered `reasoning_text` content, but emit only the supported input representation;
- `message` -> preserve role/content text and ordering, but strip response-only fields such as output item ids/status and unsupported content metadata;
- `function_call` -> preserve exact `call_id`, name, and arguments string;
- reject/explicitly handle any unexpected output type rather than silently placing arbitrary response objects into replay history.

Do not summarize, rewrite, or fabricate reasoning text. This is a wire-format projection only.

The replay history must remain semantically lossless for all fields DeepSeek requires to reconstruct thinking/tool context.

### Required tests

Use a realistic DeepSeek response fixture shaped like current API output, including:
- reasoning item with `id`, `status`, `content`, and `summary`;
- assistant message item with `id`, `status`, `content`, and output-only annotations;
- function_call item with response-only metadata where applicable.

Assert the next request:
- retains exact reasoning text;
- retains exact assistant text;
- retains exact function call id/name/arguments;
- preserves item ordering;
- contains no response-only `id` / `status` / `summary` / unsupported annotations in replay input;
- remains accepted by the local DeepSeek input-contract validator.

Update `replay_contract.json` to freeze this projection behavior.

## 2. Provider error mapping must be executable, not report-only metadata

`agentbench/deepseek_protocol/provider_error_mapping.json` exists, but the current live adapter allows SDK exceptions to propagate without applying that mapping.

This means the frozen retry semantics are not actually guaranteed for real DeepSeek/OpenAI-SDK transport failures.

Examples:
- OpenAI SDK `RateLimitError` happens to match the existing retry policy;
- `APIConnectionError` does not match frozen `ConnectionError`;
- `APITimeoutError` does not match frozen `TimeoutError`;
- 500/503 provider failures may surface as SDK status/server exceptions whose class names are not in the current retry allowlist.

DeepSeek's current API documentation says 429, 500 and 503 are retryable operational failures, while authentication/invalid-format/invalid-parameter failures should not be blindly retried.

### Required repair

Implement a provider-specific DeepSeek exception normalizer in the DeepSeek adapter layer.

It must convert actual/synthetic SDK-style exceptions into the existing ResearchCI semantic error classes/types before the shared retry policy sees them.

At minimum freeze/test mappings for:
- 401 -> `AuthenticationError`, non-retryable;
- 400 / 422 -> `InvalidRequestError`, non-retryable;
- 429 -> `RateLimitError`, retryable;
- connection failure / SDK `APIConnectionError` -> `ConnectionError`, retryable;
- SDK `APITimeoutError` / timeout -> `TimeoutError`, retryable;
- 500 / 503 -> `TransientProviderError`, retryable;
- 402 insufficient balance -> a stable non-retryable provider error classification.

The exact implementation may use status-code inspection and SDK exception attributes, but must not depend only on fragile string matching.

Update `provider_error_mapping.json` so it describes exactly the implemented behavior.

### Required tests

No network.

Create deterministic synthetic SDK-like exceptions and prove:
- retryable errors enter the existing bounded retry path without resetting step/tool/token/time budgets;
- non-retryable errors terminate after one provider attempt;
- 500/503 use frozen backoff semantics;
- no successful tool execution is replayed because of a later provider retry.

## 3. Preserve all accepted DS-0 properties

R1 must keep:
- provider = DeepSeek;
- base_url = `https://api.deepseek.com`;
- endpoint = `/responses`;
- model = `deepseek-v4-pro`;
- reasoning effort = `max`;
- top_p = 0.95;
- no temperature;
- no provider seed;
- no `previous_response_id` / `conversation` / `store` / `metadata`;
- stateless full-history replay;
- local tool argument validation;
- same authoritative `EpisodeOrchestrator` + `BudgetEnforcer`;
- 30 step / 20 custom-function / 900s / 16000 cumulative-output-token budgets;
- zero DeepSeek/OpenAI API calls;
- zero runtime network;
- zero live episodes;
- zero benchmark episodes.

Do not modify the historical OpenAI track or scientific core.

## 4. R1 freeze lineage

Do not overwrite the existing DS-0 freeze report. Create R1-specific reports and a new DeepSeek execution-protocol hash.

Parent/reference DeepSeek DS-0 protocol:

`sha256:1a74ed0bb50f615f46f1d1d83e001821a16b64d4df0e16edb8a35bcaf2d35544`

Regenerate hashes affected by:
- DeepSeek adapter source;
- replay contract;
- provider error mapping;
- shared runner/types only if changed;
- new DeepSeek DS-0-R1 composite.

Keep the historical OpenAI R2 hash unchanged.

## 5. Regression / stop rule

Run full regression.

Required:
- all existing OpenAI tests remain green;
- all existing DS-0 tests remain green or are correctly updated for the input-safe replay contract;
- new R1 replay/error-mapping tests pass;
- no external network;
- no API key access;
- no live canary;
- no benchmark episode.

Then STOP.

Phase 2B-DS-1 remains blocked until Planner accepts R1.
