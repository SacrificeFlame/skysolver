# SkySolver implementation status

Last audited: 2026-07-31  
Scope: repository `master` after commit `8cf20c8`  
Data classification: synthetic demonstration data only

## Executive assessment

SkySolver is an early-stage disruption-recovery prototype. It has useful domain primitives, a legal-first Tier 1 heuristic, basic event-sourcing mechanics, passenger examples, and an operationally focused dashboard. It is not yet an integrated or production-ready Airline Operations Control Center platform.

The main architectural risk is a gap between the target design in `architecture.md` and the runtime implementation. This document records the verified implementation state and is intentionally conservative.

## Verification baseline

Phase 0 was run on Python 3.12 with the dependencies declared in `requirements.txt`.

- Configured test baseline before Phase 0: 24 passed.
- Dashboard tests omitted by the old `pytest.ini`: 5 passed when run separately.
- Python bytecode compilation: passed.
- Tier 1 worker smoke test: passed.
- Explicit Tier 2 worker smoke test before Phase 0: failed with `AttributeError` because the result lacked a `coverage` property.

Phase 0 adds the dashboard tests to normal discovery and a regression test for the Tier 2 worker result contract.

## Capability matrix

| Area | Status | Verified behavior | Important limitation |
|---|---|---|---|
| Synthetic data | Implemented prototype | Generates crew and flight legs and groups them by hub | No external airline data contract or ingestion adapter |
| Rules engine | Partial | Checks simplified duty, flight time, rest, qualification, deadhead duration, and a loop heuristic | Not complete FAR 117; consecutive-day check is a stub; continuity and cumulative limits are absent |
| Tier 1 | Implemented prototype | Greedy legal construction, partial results, bounded execution, small reorder pass | Described as LNS, but lacks real destroy/repair neighborhoods and broader objective terms |
| Tier 2 | Scaffold | Generates legal single-leg columns and accepts a Tier 1 warm start | No Pyomo model, LP relaxation, dual pricing, branch-and-price, or real multi-leg column extension |
| Tier 3 | Partial API | Creates, ranks, approves, and rejects in-memory suggestions | Candidate generation is placeholder logic and approvals do not deploy durable schedule changes |
| Crew event state | Implemented prototype | Append-only in-memory events, replay, materialized views, JSON persistence | No optimistic concurrency, idempotency keys, schema versioning, or durable event broker |
| Partition reconciliation | Partial | Finds move requests and emits completion events | Validation, conflict handling, and durable delivery are simplified |
| Passenger recovery | Partial and duplicated | Basic rebook/waitlist decisions, route examples, priorities, and capacity reservation | Two overlapping passenger model/rules paths; Tier 2 passenger solver is simulated |
| Predictive pre-staging | Rules-based prototype | Converts synthetic signals into pre-stage actions | No trained model, historical calibration, or infrastructure scaling integration |
| Chaos replay | Synthetic harness | Runs generated partition solves and records SLA-style results | Tier 3, passenger load, failures, and several events are simulated; not a full distributed load test |
| Dashboard | Polished prototype | Presents disruption, recovery metrics, a connected airport context, solver timeline, dependency graph, and decision ledger | Much of the scenario is hardcoded; actions are not yet backed by durable operational workflows |
| Worker | Demo | Generates synthetic work and runs solver functions | Does not consume Pulsar or remain blocked on a queue despite comments and deployment intent |
| Messaging | Not implemented | Compose supplies a Pulsar service | Application code does not publish or consume Pulsar messages |
| Observability | Partial | File-backed metrics/events and Prometheus configuration | Metrics are not comprehensively exported and file writes are not a production coordination mechanism |
| Elastic deployment | Configuration example | Docker, Kubernetes, and KEDA manifests exist | Probes and autoscaling assumptions are not fully matched to working worker endpoints and metrics |
| Authentication | Demo only | Dashboard contains a simple login route | Hardcoded credentials, no session model, no RBAC, and no production security controls |

## Fully implemented within the current prototype scope

- Synthetic crew and flight-leg generation.
- Basic hub grouping.
- Pure-function legality checks for the modeled rules.
- Tier 1 legal assignment filtering and uncovered-flight reporting.
- Basic passenger rebook-or-waitlist behavior.
- Dashboard HTTP routes and static delivery.
- Local event/metrics recording for demonstrations.

“Implemented” here means the code path exists and is covered by current tests. It does not mean production-ready, certified, or proven at airline scale.

## Partial or misleading claims

### Tier 2 optimization

The source and architecture use the terms MILP, column generation, resource-constrained shortest path, and branch-and-price. The current code does not implement those algorithms. `_extend_columns` returns no extensions, and the master selection is greedy. Pyomo is declared but not used to construct a model.

### Tier 1 LNS

Tier 1 performs greedy construction followed by chronological leg reordering. It does not currently perform randomized destruction and repair or broad neighborhood search.

### Distributed event platform

Pulsar, BookKeeper, and Flink are target technologies. Their client dependencies are commented out, and normal runtime state remains in memory or JSON files.

### Elastic workers

Kubernetes and KEDA manifests demonstrate intent, but the worker is a one-shot synthetic-data command. It does not expose the health endpoints referenced by the worker deployment or consume the queue referenced by KEDA.

### Chaos/SLA claims

The replay harness is useful for deterministic demonstrations, but it does not reproduce a full distributed failure environment. Some stages use counters or sleeps. Its output must be described as synthetic benchmark output.

## Conflicting or duplicate areas

- Passenger data models exist in both `passengers/models.py` and `state/passenger_state.py`.
- Passenger rules exist in both `passengers/engine.py` and `rules/passenger_rules.py`.
- Passenger recovery exists in `passengers/engine.py` and the `solvers/passenger_tier*.py` modules.
- The custom dashboard server and the Tier 3 FastAPI application are separate services with separate in-memory state.

These should be consolidated in later phases around canonical domain models and versioned APIs.

## Production-critical gaps

1. Complete, independently reviewed regulatory rules coverage.
2. Canonical versioned domain schemas.
3. Durable event storage with concurrency and idempotency.
4. Real queue-consuming workers and backpressure.
5. Genuine Tier 2 optimization.
6. Validated Tier 3 candidates and durable approval/deployment workflows.
7. Atomic resource reservation across crew, aircraft, gates, and passengers.
8. Authentication, authorization, secrets, and attributable audit records.
9. End-to-end observability with correlation IDs.
10. Deterministic distributed load and failure testing.
11. Production data adapters and data-quality controls.
12. License selection.

## Immediate Phase 0 decisions

- Keep the target architecture document, but identify it as a target rather than current fact.
- Keep the dashboard scenario, but label it synthetic in user-facing documentation.
- Include all tests in default discovery.
- Treat explicit Tier 2 execution as an upgrade path with a Tier 1 incumbent.
- Remove test-only imports from production modules.
- Add CI for tests, compilation, and Tier 1/Tier 2 worker smoke paths.

## Next phase

Phase 1 should consolidate the canonical crew domain and replace string-only legality errors with structured, versioned violations. It should add airport and temporal continuity, overlap checks, unknown-aircraft handling, boundary tables, timezone cases, and property-based invariants before expanding solver complexity.
