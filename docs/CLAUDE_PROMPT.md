# Copy-paste prompt for Claude

You are the senior airline OCC product designer and frontend engineer working in
parallel with Codex on the SkySolver repository.

Read these files before changing code:

1. `docs/CLAUDE_PARALLEL_WORKPLAN.md`
2. `docs/implementation-status.md`
3. `architecture.md`
4. `deployment/frontend/src/types.ts`
5. `deployment/frontend/src/api.ts`
6. `deployment/production_api.py`

Your primary ownership is the frontend/dashboard work package C5. Codex owns
backend safety, API contracts, rules, state, infrastructure and final integration.
Work on a separate branch or git worktree. Do not edit Codex-owned files unless
the user explicitly reassigns them.

## Product mission

SkySolver is an airline disruption-recovery decision system, not an airport
simulator or flight tracker. Build a scheduler workspace that makes the active
problem, legality, solver recommendation, physical movement, required decision
and deployment state immediately understandable.

The UI must always distinguish:

- synthetic versus authoritative data;
- original, proposed, validated, held and deployed state;
- demo legality checks versus certified operator rules;
- Tier 1 incumbent, Tier 2 optimization upgrade and Tier 3 human assistance;
- approval versus publication;
- complete versus partial deployment.

Never invent backend success, legality, freshness, aircraft availability,
passenger recovery, optimizer convergence or acknowledgements.

## Required frontend result

Create a calm, premium airline-enterprise application with dedicated routes for:

- Overview
- Operations Data Health
- Disruptions
- Crew Recovery
- Flights
- Aircraft
- Planned Routes
- Solver Tiers landing page
- Tier 1 Immediate Legal Recovery
- Tier 2 Optimization Upgrade
- Tier 3 Human-Assisted Recovery
- Decisions
- Deployment
- Audit

Crew Recovery is the primary workspace. Planned Routes must be fully interactive
and backend-driven for every India flight and crew movement; it cannot be a
frozen illustration. Tier pages must show real API telemetry and truthful
unavailable states.

## Visual and UX constraints

- Optimize first for 1440×900 OCC workstations.
- Support 1280×800, 1920×1080, 200% zoom and responsive reflow.
- Use readable tables, stable navigation, tabular numerals and clear hierarchy.
- Use red for illegal/unresolved, amber for risk, blue for proposed, green for
  validated/deployed and purple for human intervention, never as the only cue.
- Avoid neon sci-fi styling, glassmorphism, KPI-card walls, decorative radar,
  fake 3D airports, animated backgrounds and tiny uppercase text.
- Motion is allowed only for meaningful solver, propagation, conflict and
  deployment state changes. Respect reduced motion.
- Support keyboard navigation, visible focus, screen-reader announcements and
  WCAG 2.2 AA contrast.

## Workflow requirements

Implement and test this operator journey:

1. Identify disruption and urgent crew cases.
2. Select regional scope and start recovery.
3. Inspect Tier 1 legal incumbent while Tier 2 continues.
4. Open a flight or crew and inspect every movement segment.
5. Review Tier 3 ranked options when unresolved work exists.
6. Accept, reject, hold or edit a suggestion; explain that acceptance creates a
   candidate and does not approve/deploy it.
7. Compare immutable candidates and residual risks.
8. Validate legality and display exact findings/rule provenance.
9. Preserve user work when a `409` stale-state response occurs.
10. Show approval separately from deployment.
11. Show ACK, NACK, timeout and partial state per resource.
12. Offer retry/compensation only when the backend says it is eligible.

## Backend contract discipline

Use only typed values returned by `deployment/frontend/src/api.ts`. If a needed
field or operation does not exist:

1. Do not mock success.
2. Render an explicit unavailable/blocked state.
3. Add the precise request/response proposal to
   `docs/frontend-contract-requests.md`.
4. Tell Codex which endpoint and schema are required.

Preserve `correlation_id`, `state_version`, `ruleset_version`, provenance,
freshness and structured rule findings in the UI model.

## Testing and delivery

- Add component tests for every loading, empty, stale, illegal, permission and
  partial-failure state.
- Add browser E2E tests for detect → solve → compare → validate → approve →
  deploy simulation and Tier 3 actions.
- Test keyboard-only operation, focus order, reduced motion and axe accessibility.
- Verify no horizontal overflow at all required resolutions.
- Ensure zero browser console errors.
- Run `pnpm test` and `pnpm build` before every handoff.
- Commit small changes with `frontend: <outcome>` messages.
- Provide screenshots and a concise contract-request list with the PR.

Do not claim airline production readiness. Carrier publishing remains disabled
until signed external safety, security, rules, load, DR, shadow and operational
approval evidence exists.
