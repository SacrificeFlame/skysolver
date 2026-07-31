# SkySolver implementation status

Last audited: 2026-07-31  
Data classification: realistic synthetic demonstration data only

## Executive assessment

SkySolver is now an integrated disruption-recovery reference implementation: legal-first crew recovery, regional state streams, tiered degradation, durable human decisions, passenger prototypes, versioned operations APIs, health probes, autoscaling manifests, chaos replay, and an operational dashboard all exist in one repository. It remains a prototype—not a certified airline production system.

## Implemented and verified

| Capability | Runtime behavior | Boundary |
|---|---|---|
| Canonical contracts | Structured rule violations, recovery tiers, audit/correlation metadata | Legacy passenger types still need consolidation |
| Legality layer | Duty/flight/rest, qualifications, unknown types, positioning, continuity, connection/overlap, deadhead safeguards | Synthetic FAR 117-style subset; requires regulatory review and complete cumulative/consecutive rules |
| Tier 1 | Bounded legal greedy construction with local improvement and explicit uncovered work | Improvement neighborhood remains intentionally lightweight |
| Tier 2 | Warm-started legal multi-leg column generation and time-boxed set-cover selection | Master is a deterministic combinatorial heuristic, not a certified MILP/CP-SAT optimizer |
| Tier orchestration | Legal Tier 1 incumbent, Tier 2 upgrade, explicit Tier 3 escalation | Runs synchronously inside the reference worker |
| Tier 3 | Legality-gated ranked suggestions and SQLite decision ledger | Approved changes are audited but not sent to a carrier schedule system |
| Event state | Append-only streams, deterministic replay, idempotency, sequence numbers, optimistic concurrency, correlation IDs | In-memory/JSON reference adapter; production needs a transactional durable broker/store |
| Partitioning | Hub-local solving and cross-partition move reconciliation | Reconciliation validation remains simplified |
| Passenger recovery | Synthetic routing, priorities, capacity and compensation examples | Duplicate legacy passenger modules remain; no atomic multi-resource commit |
| Operations API | Versioned disruptions, flights, recoveries, candidates, decisions, validation, deployment, rollback, audit and SSE contracts with optimistic versions | Custom HTTP reference server and process-local workflow store, not a hardened API gateway |
| Dashboard | React/TypeScript viewport-height OCC with digital twin, dependency graph, plan comparison, network impact, solver timeline, audit and command palette | Airport scenario and metrics are explicitly synthetic demo data |
| Elastic operations | Worker health server, Kubernetes resources/probes and KEDA example | Queue consumer remains an adapter seam; Pulsar is not active in this build |
| Verification | Unit/integration suite, compilation, two worker smokes, orchestration/state CI gates | Elliott harness is synthetic single-process replay, not a distributed carrier-scale proof |

## Phase mapping

1. Architecture and honest maturity documentation: complete for prototype scope.
2. Tests-first legality engine: complete for the documented synthetic ruleset.
3. Tier 1 solver: complete for prototype scope.
4. Tier 2 upgrade path: integrated; mathematical optimizer remains the largest algorithmic gap.
5. Tier 3 interface: usable API and durable decision history; deployment adapter outstanding.
6. Event state and partition reconciliation: core concurrency/idempotency complete; production storage adapter outstanding.
7. Chaos/replay: present with explicit synthetic limitations.
8. Deployment: containers, worker probes, health API and autoscaling examples present.
9. Product UI: disruption-centric dashboard and versioned data contract present.

## Production blockers

- Independent FAR 117/company-contract certification and exhaustive boundary/property tests.
- A genuine MILP/CP-SAT or branch-and-price Tier 2 with measured optimality gaps.
- Durable queue consumption, retries/dead-lettering, transactional projections and backpressure.
- Atomic crew/aircraft/gate/passenger reservation and carrier-system deployment adapters.
- SSO, RBAC, CSRF/session controls, managed secrets, tenant isolation and immutable external audit storage.
- Distributed Elliott-scale load/chaos evidence against the stated SLA.
- Production data contracts, privacy controls, disaster recovery, runbooks and formal release governance.

No benchmark in this repository should be represented as real-carrier performance or regulatory certification.
