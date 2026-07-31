# SkySolver v2 Architecture

> **Target architecture, not a statement of current deployment.** The verified
> Python reference implementation and its remaining gaps are tracked in
> `docs/implementation-status.md`. Rust, Pulsar, Flink and Drools below are
> evaluated production targets unless explicitly marked live.

## 1. Overview

SkySolver v2 is a resilient crew rescheduling engine designed to avoid the catastrophic failure modes of its predecessor during high-stress events. The system employs **regional partitioning**, **tiered solving with graceful degradation**, **event-sourced state**, and **elastic compute** to ensure continuous operation under load.

**Key Design Principle:** *Degrade gracefully, never fail hard.*

---

## 2. Regional Partitioning Strategy

### 2.1 Partition Definition
The crew/aircraft network is decomposed by **hub-based regions**:
- **Primary hubs:** Major airports (e.g., DEN, ORD, ATL, LAX, MIA, DFW, EWR)
- **Secondary hubs:** Significant airports with sufficient crew base
- **Regional clusters:** Grouping of smaller airports served by a primary hub

Each partition contains:
- Flights originating/terminating within the region
- Crew members whose base is in that region
- Aircraft assigned to that region

### 2.2 Partition Isolation
- **Compute isolation:** Each partition runs in its own Kubernetes namespace with resource quotas
- **State isolation:** Event streams are partitioned by hub ID; no cross-partition reads during solve
- **Failure containment:** A partition can degrade to Tier 3 without blocking others

### 2.3 Cross-Partition Reconciliation
For crews that legally need to move between partitions (e.g., deadheading to another hub):

1. **Legal Move Queue:** When a crew member is assigned to a flight outside their partition, a `LEGAL_MOVE_REQUEST` event is emitted
2. **Reconciliation Pass:** Post-solve, a lightweight reconciler:
   - Validates the move is duty-time compliant across partitions
   - Updates crew location in target partition's event stream
   - Emits `LEGAL_MOVE_COMPLETED` event
3. **Grace Period:** Moves can be "in flight" for up to 6 hours before reconciliation is required

**Failure Mode:** If cross-partition moves exceed 15% of total crew, system alerts but continues — the move is simply deferred to the next cycle.

---

## 3. Tiered Solving Design

### 3.1 Tier 1: Fast Heuristic Solver (≤ 1 second per partition)

**Algorithm:** Large Neighborhood Search (LNS) with greedy destruction/reconstruction
- **Destruction:** Remove 10-20% of assignments (weighted random, favoring high-disruption flights)
- **Reconstruction:** Greedy insertion with hard legality checks
- **Local search:** 2-opt swaps for duty-time minimization

**Guarantees:**
- All assignments satisfy FAR 117 duty-time, rest periods, and qualifications
- No crew deadheading loops (checked by rules engine)
- Solution quality: typically 85-95% of optimal cost

**Implementation:** Single-threaded Rust worker with async event reads

### 3.2 Tier 2: Near-Optimal Optimizer (≤ 5 minutes per partition)

**Algorithm:** Column Generation with Branch-and-Price
- **Master problem:** Set covering for crew pairings
- **Subproblem:** Shortest path with resource constraints (duty-time)
- **Initial columns:** Generated from Tier 1 solution as warm start

**Time Management:**
- Solves in parallel with Tier 1
- If converged before 5 minutes: upgrades Tier 1 solution
- If not: Tier 1 solution is used (never blocks)

**Failure Mode:** Solver timeout → fall back to Tier 1

### 3.3 Tier 3: Human-Assisted Mode

**Trigger:** Both Tier 1 and Tier 2 exceed time budgets

**Output:** Ranked list of AI-suggested reassignments
- **Format:** JSON API + minimal web UI (React + Tailwind)
- **Ranking criteria:**
  1. Legal compliance (hard filter)
  2. Duty-time cost (minimize disruption)
  3. Crew seniority fairness
  4. Passenger impact (gate changes, connections)

**UI Features:**
- Toggle: "Auto-approve all" (for routine disruptions)
- Review queue with acceptance/rejection per crew
- "Why this suggestion?" explainer showing constraint satisfaction

**SLA:** Must produce suggestions within 30 seconds of trigger

---

## 4. Data Model

### 4.1 Event-Sourced Crew State

```
Events (append-only, immutable):
├── CREW_MEMBER_CREATED {crew_id, name, base_hub, qualifications}
├── FLIGHT_ASSIGNED {crew_id, flight_id, phase, timestamp}
├── DUTY_START {crew_id, duty_id, start_time}
├── DUTY_END {crew_id, duty_id, end_time}
├── REST_PERIOD_START {crew_id, rest_id, start_time}
├── QUALIFICATION_ADDED {crew_id, qualification, effective_date}
├── LEGAL_MOVE_REQUEST {crew_id, from_partition, to_partition, reason}
└── SCHEDULE_REJECTED {crew_id, flight_id, reason}
```

**Read Model:** Materialized view updated by event handlers
- `crew_status` table: current duty clock, location, active assignments
- Updated within 100ms of event append (CQRS pattern)

### 4.2 Flight Data

Flights are read-only from external scheduling system, with:
- `flight_events` stream: cancellations, gate changes, delays
- `flight_leg` entity: origin, destination, scheduled times

### 4.3 Qualification Model

```
Qualification {
  code: string,           // e.g., "B737", "ICAO_WX", "NIGHT_FLYING"
  valid_from: date,
  valid_to: date,
  source: "CERT" | "TRAINING" | "MEDICAL"
}
```

---

## 5. Tech Stack Justification

### 5.1 Compute & Orchestration

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Orchestration | Kubernetes | Native autoscaling, resource quotas per partition |
| Worker Pool | KEDA (Kubernetes Event-Driven Autoscaling) | Scales workers based on partition queue depth |
| Container Runtime | containerd | Faster startup than Docker |
| Language | Rust (solvers), Python (rules), Go (infra) | Performance-critical code in Rust, rapid iteration in Python |

### 5.2 Event Streaming

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Event Log | Apache Pulsar | Multi-tenancy, geo-replication, built-in partitioning |
| Event Store | Apache BookKeeper | Write-once-read-many, low latency |
| Stream Processing | Apache Flink | Exactly-once processing, stateful functions |

### 5.3 Rules Engine

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Rules DSL | Drools (embedded) | Mature, well-tested for regulatory compliance |
| Validation API | gRPC service | Low-latency calls from solvers |
| Test Harness | JUnit 5 + parameterized tests | Full coverage of FAR 117 scenarios |

### 5.4 Human Interface

| Component | Technology | Rationale |
|-----------|------------|-----------|
| UI Framework | React 18 + Tailwind CSS | Fast, responsive, accessible |
| Backend | FastAPI (Python) | Auto-generated OpenAPI docs, easy testing |
| State Management | SWR + React Query | Stale-while-revalidate for real-time updates |

---

## 6. Observability & Chaos Testing

### 6.1 Metrics
- **Per-partition:** solve_time, tier_used, crew_disruption_score
- **System-wide:** cross_partition_moves, legal_violations, SLA_breaches
- **Alerting:** PagerDuty integration for SLA breaches

### 6.2 Chaos Replay Harness

**Test Profile: "Winter Storm Elliott Scale"**
- 16,700 flight cancellations
- 1,200 crew members affected
- Simulated in 15 regional partitions

**SLA Definition:**
```
Tier 1: 100% of affected crew have legal solution within 5 minutes
Tier 2: 60% of partitions converge to better solution within 5 minutes
Tier 3: All partitions produce human-reviewable output within 30 seconds of trigger
```

**Chaos Scenarios:**
- Worker node failures (random kill)
- Event stream partition outage
- Rules engine latency spike
- Cross-partition move storm (15%+ crew moving)

**Build Gate:** Tests must pass in CI; build fails if SLA breached

---

## 7. Failure Modes Summary

| Component | Failure Mode | Degradation |
|-----------|--------------|-------------|
| Tier 1 solver | Worker crash | Re-queue, retry on different node |
| Tier 2 solver | Timeout | Use Tier 1 solution |
| Rules engine | Unavailable | Cache last-known-good rules, alert |
| Event stream | Partition unavailable | Solve affected partition in degraded mode |
| Cross-partition reconciler | Backlog | Defer moves, reconcile in next cycle |
| Human UI | Down | API-only mode, suggestions still generated |

---

## 8. Next Steps

1. [ ] Implement FAR 117 rules engine (Phase 2 deliverable)
2. [ ] Build Tier 1 heuristic solver with synthetic data
3. [ ] Add Tier 2 optimizer integration
4. [ ] Create human-assist UI
5. [ ] Deploy event-sourced state layer
6. [ ] Implement chaos/replay harness
7. [ ] Configure elastic worker pool
