# Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-FREEZE-R0

## Planner Instruction

You are the Executor (Codex) for ResearchCI.

This phase is NOT live execution.

The goal is to create an immutable execution freeze point before any provider request.

## Current problem

Previous Grant reissue correctly rejected stale bindings:

- Grant target SHA differed from current HEAD
- Execution artifacts became stale after commit creation

This phase must eliminate artifact self-invalidation.

## Objective

Create an immutable execution target manifest.

The execution chain must bind:

```
Execution Target SHA
    |
    +-- Execution Config
    |
    +-- Execution Auth
    |
    +-- Approval
    |
    +-- Grant
    |
    +-- Credential Source
```

## Rules

1. Freeze one exact repository SHA.
2. Any SHA mismatch MUST reject before execution.
3. Do not acquire credential before all checks pass.
4. Do not call provider network.
5. Do not modify security core.

## Hard Stop Conditions

Immediately stop with rejection if any occurs:

### SHA mismatch

```
artifact_sha != frozen_execution_sha
```

Result:

```
REJECT_BEFORE_EXECUTION
```

No credential access.
No network.

### Artifact chain mismatch

Any mismatch among:

- config
- auth
- approval
- grant
- credential source

Result:

```
CHAIN_INVALID
```

### Credential violation

Stop if:

- credential callback called early
- credential persisted
- credential logged
- secret enters evidence

Result:

```
SECURITY_ABORT
```

### Network violation

Only future allowed request:

```
GET /models
max_requests=1
```

Any other request:

```
NETWORK_SCOPE_VIOLATION
```

### Retry violation

No:

- automatic retry
- SDK retry
- manual retry

Result:

```
EXECUTION_ABORT
```

### Repository mutation

If HEAD changes after freeze:

```
EXECUTION_INVALIDATED
```

## Required Deliverables

Create:

```
agentbench/reports/phase2b_ds1_execution_freeze_r0.json
agentbench/reports/phase2b_ds1_execution_freeze_r0.md
agentbench/reports/phase2b_ds1_execution_freeze_r0_scope_audit.json
```

Manifest must include:

- frozen SHA
- artifact SHA bindings
- provider scope
- runtime binding
- abort rules
- credential policy

## Testing

Run offline tests only.

Requirements:

- no provider API calls
- no network
- no credential reads
- no live canary

Maintain regression.

## Final response format

```
Phase 2B-DS-1-LIVE-PREFLIGHT-EXECUTION-FREEZE-R0 COMPLETE / OFFLINE

Commit:
Remote HEAD:
Working tree:

Frozen SHA:
Artifact binding:

Tests:

Provider API calls: 0
Network calls: 0
Credential reads: 0

Final status:

EXECUTION_FREEZE_READY
/
FAILED

STOP
```
