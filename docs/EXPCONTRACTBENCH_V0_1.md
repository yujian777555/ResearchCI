# ExpContractBench v0.1

## 1. Benchmark objective

ExpContractBench measures whether ResearchCI detects and prevents explicit experiment-contract violations with deterministic ground truth.

The benchmark is not a dishonesty benchmark and does not require an LLM judge.

## 2. Frozen violation taxonomy

| Rule | Violation | Definition | Earliest enforcement |
|---|---|---|---|
| RCI-C001 | Seed-set mismatch | Baseline/candidate observed seed sets violate the declared paired seed set | pre-aggregate |
| RCI-C002 | Budget mismatch | A comparison-sensitive training/evaluation budget differs without authorization | pre-run |
| RCI-C003 | Split drift | Baseline/candidate use different dataset split fingerprints | pre-run |
| RCI-C004 | Unauthorized config drift | Candidate changes a comparison-sensitive field outside `allowed_to_change` | pre-run |
| RCI-C005 | Stale cache reuse | Cached artifact provenance does not match current invalidation keys | pre-cache-consume |
| RCI-C006 | Failed-run omission | A declared failed run is silently omitted from aggregation | pre-aggregate |

## 3. Canonical case layout

```
cases/
└── case_0001/
    ├── repo/
    ├── contract.yaml
    ├── run_intents/
    ├── run_results/
    ├── artifacts/
    └── ground_truth.json
```

Example ground truth:

```json
{
  "case_id": "case_0001",
  "repo_id": "tabular_sklearn",
  "is_valid": false,
  "violation": {
    "rule_id": "RCI-C002",
    "type": "budget_mismatch",
    "stage": "pre_run",
    "location": "candidate.training.max_epochs"
  },
  "before": 100,
  "after": 150,
  "expected_action": "block",
  "repair": {
    "operation": "set",
    "path": "candidate.training.max_epochs",
    "value": 100
  }
}
```

## 4. MVP dataset size

Frozen target:

- 3 controlled ML repositories;
- 6 violation classes;
- 10 injected variants per class per repository;
- 180 violating cases total;
- 20 valid controls per repository;
- 60 clean cases total;
- **240 cases overall**.

Repository families:
1. scikit-learn tabular classification;
2. small PyTorch classification;
3. small text-classification pipeline.

Use small CPU-friendly workloads wherever possible.

## 5. Injection diversity

Injectors must vary the surface form of a rule violation.

Examples for RCI-C002:
- epoch mismatch;
- max-step mismatch;
- evaluation-budget mismatch;
- training-sample-count mismatch.

Examples for RCI-C004:
- batch-size drift;
- augmentation drift;
- model-width drift;
- preprocessing drift;
- optimizer drift when optimizer is not permitted.

The benchmark must not be solvable by recognizing one hard-coded field name.

## 6. Determinism

Every generated case must be reproducible from:
- benchmark version;
- source repository fixture version;
- injector name;
- injector seed.

Generation must be idempotent.

## 7. Evaluation outputs

Each checker produces:
- `decision`: PASS/BLOCK;
- `rule_ids`: zero or more detected rule IDs;
- `locations`: canonical paths;
- `stage`: detection stage;
- `repair`: optional deterministic repair operation.

## 8. Metrics

Primary:
- Invalid Experiment Escape Rate (IER).

Secondary:
- Violation Recall;
- Violation Precision;
- False Block Rate;
- Rule-ID Accuracy;
- Violation Localization Accuracy;
- Repair Success Rate;
- Detection Stage;
- Runtime Overhead;
- Prevented Invalid Compute.

## 9. Invalid Experiment Escape Rate

```
IER =
  violating cases reaching evidence stage
  ---------------------------------------
          all violating cases
```

A post-hoc detection counts as escaped if the invalid experiment already reached the evidence stage.

## 10. False Block Rate

```
FBR =
  valid cases incorrectly blocked
  -------------------------------
           all valid cases
```

A system that blocks everything is therefore not competitive.

## 11. Repair success

A repair is successful only when:
1. the proposed deterministic repair is applied;
2. the original violation disappears;
3. no new violation is introduced;
4. the case revalidates to PASS.

No LLM judge is used.

## 12. Phase-1 vertical slice

The first implementation does **not** generate all 240 cases.

It first implements:
- contract schema;
- canonical manifests;
- RCI-C001;
- RCI-C002;
- small deterministic fixtures proving valid and invalid paths.

The full six-rule benchmark is unlocked only after this vertical slice passes review.
