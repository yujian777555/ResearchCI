# ResearchCI

**ResearchCI** is a semantic CI system for autonomous machine-learning research.

Ordinary CI asks whether code builds and tests pass. ResearchCI asks whether a proposed experiment is still scientifically comparable to its baseline.

The project compiles experiment protocols into executable repository-level contracts and enforces them across code, configuration, data, runs, caches, aggregations, and artifacts.

## Current phase

Specification Freeze v0.1 is complete. Phase 1 implements a minimal vertical slice:
- contract schema and parser;
- canonical experiment manifests;
- RCI-C001 Seed-set mismatch;
- RCI-C002 Budget mismatch;
- deterministic tests and benchmark fixtures.

See:
- `docs/EXPERIMENT_CONTRACT_V0_1.md`
- `docs/EXPCONTRACTBENCH_V0_1.md`
- `docs/MVP_EXPERIMENT_PROTOCOL.md`
