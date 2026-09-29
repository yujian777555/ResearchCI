# MVP Experiment Protocol

## 1. Research question

> Given an explicit experiment contract, can ResearchCI reliably prevent scientifically incomparable ML experiments from entering the evidence pipeline?

Phase 1 intentionally does not test whether ResearchCI makes an autonomous scientist more intelligent.

## 2. Phase-1 architecture

```
Contract Parser
      |
      v
Manifest Builder
      |
      v
Canonical Experiment State
      |
      v
Invariant Engine
      |
   PASS / BLOCK
      |
      v
Repair Hint
```

The rule engine is deterministic in Phase 1:
- no model training;
- no embeddings;
- no LLM reviewer;
- no agent orchestration.

## 3. Frozen baselines

- **B0 No Check**: execute without validation.
- **B1 Schema Validation**: validate syntax/schema only.
- **B2 Provenance-Only**: validate hashes and artifact lineage only.
- **B3 Post-hoc ResearchCI**: evaluate contract after the experiment completes.
- **Ours Runtime ResearchCI**: enforce at the earliest valid lifecycle stage.

Agent-specific baselines are reserved for Phase 2.

## 4. Primary metric

**Invalid Experiment Escape Rate (IER)**.

A violation is an escape if it reaches the evidence/aggregation stage before being blocked.

## 5. Secondary metrics

- Violation Recall;
- Violation Precision;
- False Block Rate;
- Rule-ID Accuracy;
- Violation Localization Accuracy;
- Repair Success Rate;
- Detection Stage;
- Runtime Overhead;
- Prevented Invalid Compute.

## 6. Detection timing

Runtime enforcement must be distinguished from post-hoc detection.

Example:

```
Post-hoc:
invalid 150-epoch job
  -> consumes compute
  -> finishes
  -> violation discovered

Runtime ResearchCI:
invalid 150-epoch RunIntent
  -> pre-run check
  -> BLOCK
```

Both may achieve 100% recall, but only runtime enforcement prevents invalid compute and prevents contaminated evidence from being created.

## 7. Prevented Invalid Compute

For a blocked experiment, estimate the compute that would otherwise have been consumed.

The benchmark may use deterministic declared cost units before introducing GPU-hour estimates.

## 8. Frozen Phase-1 GO gate

The complete six-rule v0.1 benchmark may proceed to Agent Stress Testing only when all are satisfied:

- overall Violation Recall >= 95%;
- per-rule Recall >= 90%;
- False Block Rate <= 5%;
- Invalid Experiment Escape Rate <= 5%;
- Rule-ID Accuracy >= 95%;
- benchmark generation reproducibility = 100%.

Repair target:
- Repair Success Rate >= 90%.

Failure of these gates blocks claims of effective runtime enforcement and blocks Phase 2.

## 9. Phase roadmap

```
Phase 0
Novelty + Specification
COMPLETE

Phase 1
ExpContractBench
Contract Engine
Six deterministic rules

Phase 2
Autonomous Research Stress Test

Phase 3
Real-repository generalization

Phase 4
Paper + ablations + release
```

## 10. Current Phase-1 vertical slice

Implement only:
1. contract schema/parser;
2. canonical `RunIntent` / `RunResult` / `AggregateIntent`;
3. RCI-C001 Seed-set mismatch;
4. RCI-C002 Budget mismatch;
5. deterministic valid/invalid fixtures;
6. tests for pass/block, rule ID, localization, and repair.

Do not implement C003-C006 until Planner review.

## 11. Non-goals

Do not add in Phase 1:
- AI Scientist workflow;
- paper generation;
- citation verification;
- novelty checking;
- p-hacking detection;
- natural-language research ethics judgments;
- learned rule models;
- LLM-based judges.

The core positioning remains:

> Ordinary CI checks whether the code can run. ResearchCI checks whether the experiment can still be fairly compared.
