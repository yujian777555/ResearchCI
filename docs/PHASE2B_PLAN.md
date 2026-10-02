# Phase 2B Plan

## Objective
Evaluate Runtime ResearchCI under controlled live-agent execution without modifying frozen Phase 1 contracts.

## Conditions
- A0 No Check
- A1 Schema Validation
- A2 Provenance Only
- A3 Post-hoc ResearchCI
- A4 Runtime ResearchCI

## Agent Protocol
Freeze:
- model identifier
- temperature
- system prompt
- tools
- max steps
- seeds

## Trial Design
Pilot:
18 scenarios x 5 conditions x 3 runs = 270 episodes

Extension:
18 x 5 x 10 runs

## Metrics
Primary:
- CIER
- EIFR
- VTCR

Secondary:
- tool calls
- runtime
- token usage
- repair efficiency

## Statistics
Use paired evaluation, bootstrap confidence intervals, and Wilcoxon signed-rank testing.

## Failure Taxonomy
- F1 Constraint violation
- F2 Evidence fabrication
- F3 Invalid recovery
- F4 Exploration failure
- F5 Over-constraint

## Scope
Do not modify C001-C006 semantics or Phase 1 benchmark artifacts.
