# Design QA — Airline Recovery Workspace

Visual target: the selected combined Option 1 + Option 3 airline OCC direction, expanded into the approved multi-workspace information architecture.

Viewport tested: 1440 × 900.

## Results

- P0: none.
- P1: none.
- P2: none.
- P3: some secondary tables intentionally scroll inside their workspace at lower-height desktop resolutions.
- The global application shell, active disruption, data freshness, solver health, worker capacity, operator identity, and synthetic-data state remain visible across routes.
- Dedicated routes verified for Overview, Disruptions, Crew Recovery, Flights, Aircraft, Planned Routes, Solver Tiers, Tier 1, Tier 2, Tier 3, Decisions, Deployment, and Audit.
- Planned Routes shows scheduled and proposed routes, weather conflict, origin/destination, route duration, crew movement chain, and movement feasibility checks.
- Crew Recovery exposes the original and proposed assignment, duty legality, physical movement, passenger impact, residual risk, ruleset, and state version.
- The recovery workflow was exercised through solve → approve → independent validation → deployment handoff.
- Browser console errors: none.
- Overview document height equals viewport height at 1440 × 900.
- Product-level synthetic values are explicitly labelled and existing backend legality/deployment responses remain authoritative.

final result: passed
