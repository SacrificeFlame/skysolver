# SkySolver MVP

## The product

SkySolver is a hackathon-ready airline disruption recovery workspace for crew schedulers and Operations Control Centre teams. It turns a disruption into a visible, reviewable recovery workflow: identify affected operations, produce legal recovery options, compare their impact, approve a plan, and simulate deployment.

**One-line pitch:** SkySolver helps an airline recover from disruption by finding legal crew and aircraft assignments quickly, then showing operators exactly what changed and why.

## The problem

Weather, aircraft restrictions, airport congestion, and crew-duty limits can turn one delayed flight into a network-wide cascade. Schedulers must answer several connected questions under time pressure:

- Which flights have become uncovered or delayed?
- Which crews are illegal, out of position, or close to a duty limit?
- Which aircraft and passenger connections are affected?
- What is the fastest legal recovery plan?
- Which decisions still need a human?

SkySolver brings those questions into one decision-support workflow rather than presenting an airport animation or a collection of disconnected metrics.

## Who it is for

- **Crew schedulers** reviewing and approving legal reassignments.
- **Operations controllers** coordinating flights, aircraft, airports, and recovery actions.
- **Recovery managers** comparing plans and monitoring network restoration.
- **Supervisors and judges** reviewing decisions, explanations, and an audit trail.

## What the MVP demonstrates

The MVP ships with a realistic synthetic Indian airline disruption scenario and provides:

1. **Network overview** — disruption severity, recovery progress, affected flights, crew legality, aircraft constraints, passenger exposure, and pending decisions.
2. **Disruption workspace** — the disruption scope and its propagation across operational resources.
3. **Crew recovery worklist** — urgent crew problems, proposed replacements, duty context, and legality evidence.
4. **Tier 1 recovery** — a fast heuristic that attempts to establish a legal incumbent quickly.
5. **Tier 2 optimization** — a time-boxed optimization path that attempts to improve the Tier 1 result without blocking it.
6. **Tier 3 assistance** — a usable queue of unresolved cases and ranked human-review suggestions.
7. **Planned Routes** — an interactive Indian network map with a distinct route for each selected flight, plus aircraft rotations and crew movements.
8. **Candidate comparison** — recovery plans compared by coverage, delay, operational impact, and residual risk.
9. **Validation and decisions** — illegal actions are blocked; review actions retain their state and explanation.
10. **Deployment simulation and audit** — approved recovery actions progress through simulated acknowledgements and appear in an attributable event history.

## Demo flow

1. Open the dashboard and sign in with the demo account.
2. Start on **Overview** and identify the active disruption and highest-priority impact.
3. Open **Crew Recovery** and select an uncovered or illegal assignment.
4. Inspect the proposed crew movement, remaining duty time, and legality result.
5. Open **Solver Tiers** to show that Tier 1 remains available while Tier 2 improves the plan and Tier 3 retains human control.
6. Open **Planned Routes**, select different flights, and show that every aircraft has its own Indian route and operational context.
7. Compare candidates in **Decisions**, validate the chosen plan, and approve it.
8. Use **Deployment** to simulate publication and acknowledgements.
9. Finish in **Audit** to show the recorded recovery history.

## Architecture

- **Frontend:** React, TypeScript, and Vite; page-based OCC workspaces with a shared typed state and API layer.
- **Backend:** FastAPI services exposing versioned recovery, flight, crew, route, decision, deployment, audit, and event interfaces.
- **Decision engine:** a dedicated legality layer plus tiered heuristic, optimization, and human-assist recovery paths.
- **Data:** realistic synthetic Indian airline fixtures passed through the same application contracts used by the UI.
- **Hosting:** a single Railway deployment that serves the API and compiled dashboard.

## Inputs and outputs

### Inputs

- Flight schedules and operating times.
- Crew assignments, locations, qualifications, rest, and duty state.
- Aircraft locations, rotations, and restrictions.
- Airport and disruption information.
- Passenger counts and connection exposure.
- Recovery priorities and operator decisions.

### Outputs

- Legal recovery candidates and unresolved cases.
- Crew reassignments and positioning movements.
- Aircraft swaps and revised operational routes.
- Expected delay and passenger-impact changes.
- Validation findings, recommendations, and explanations.
- Simulated deployment acknowledgements and audit events.

## Safety and truthfulness

This is a **hackathon MVP and decision-support demonstration**, not a certified airline operations system. It uses synthetic data and does not publish to a live carrier. Its DGCA-oriented legality examples are not a substitute for a carrier-approved, certified rules package. Production use would require authoritative integrations, independent rules certification, security approval, segregation of duties, resilience testing, and controlled operational rollout.

## MVP success criteria

The demo succeeds when a new viewer can, within seconds:

- identify the disruption and its most urgent impact;
- see which flight, crew, aircraft, and passengers are affected;
- understand which solver tier produced a recommendation;
- inspect a flight-specific route and crew positioning chain;
- distinguish proposed, validated, deployed, and unresolved work;
- complete the recovery story without encountering a dead control.

## Deliberate MVP limits

- Synthetic scenario data rather than live airline feeds.
- Simulated publication rather than carrier-system writes.
- Demonstration-scale state storage rather than a production event platform.
- DGCA-oriented sample constraints rather than certified operator rules.
- Simplified cost, passenger, maintenance, and airport-resource models.

These boundaries keep the project credible: the MVP demonstrates the complete recovery workflow without claiming production authority it does not yet have.

## Next steps after the hackathon

1. Connect read-only airline schedule, crew, aircraft, airport, and passenger adapters.
2. Certify effective-dated DGCA and operator-specific rules with domain experts.
3. Replace demo persistence with durable event-sourced state and replayable projections.
4. Benchmark the solver on production-shaped disruption graphs and failure scenarios.
5. Run in shadow mode beside an airline's current process before enabling controlled writes.

## 30-second pitch

Airline disruptions are not just delayed aircraft—they are a rapidly changing constraint problem involving crew legality, aircraft position, passenger connections, and operational deadlines. SkySolver gives schedulers a legal plan quickly, keeps improving it in parallel, and hands unresolved cases to a human instead of failing. Every recommendation is visible, explainable, and connected to the flight and route it changes. This MVP demonstrates that complete recovery loop on a synthetic Indian airline network.
