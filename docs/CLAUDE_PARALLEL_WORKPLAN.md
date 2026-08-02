# SkySolver Codex + Claude parallel implementation plan

Status baseline: 2026-08-01
Authority: synthetic/shadow only; carrier writes remain disabled
Baseline verification: 148 Python tests, 5 frontend tests, TypeScript check and Vite production build pass

## Coordination contract

Codex owns the integration branch and final safety review. Claude works on a
separate branch/worktree and submits small commits grouped by the work packages
below. Neither agent may enable carrier writes, claim regulatory certification,
or weaken a failing gate to make tests pass.

Before each package:

1. Rebase on the latest integration branch.
2. Claim the package and named files in the PR description.
3. Add tests before or with implementation.
4. Do not modify files owned by the other lane without a handoff note.
5. Preserve correlation IDs, tenant IDs, optimistic versions and provenance.
6. Treat `409`, `422`, partial deployment and stale data as first-class outcomes.
7. Commit one package at a time using `area: outcome` messages.

Codex merges only after the package-specific tests and the complete suite pass.

## Current implemented foundation

- FastAPI/OpenAPI recovery API and India-focused React scheduler workspace.
- Tier 1 legal incumbent, restricted-master MILP Tier 2 and authenticated Tier 3.
- DGCA-oriented demo rules, signed package governance and separate validation service.
- Canonical models, ingestion engine, Data Health interlocks and resource holds.
- Aurora event/outbox repository, MSK IAM producer, projection schema and partition sagas.
- Deployment ACK/NACK/timeout/partial/compensation state machine.
- OIDC/RBAC/MFA step-up, immutable S3 Object Lock artifacts and signed release evidence.
- EKS/Aurora/MSK/Redis/S3/KMS/Cognito/ALB/WAF/DNS/backup/Prometheus Terraform baseline.

## Claude lane — durable data plane

### C1. Aurora-backed recovery workflow store

Owned files:

- `state/durable_recovery_store.py` (new)
- `state/workflow_projections.py` (new)
- `infrastructure/migrations/004_idempotency_and_workflow_commands.sql` (new)
- `tests/test_durable_recovery_store.py` (new)

Deliver:

- Implement the complete store protocol currently exercised by `RecoveryStore`.
- Append each accepted mutation and transactional outbox event atomically.
- Read recovery, candidate, approval, hold and deployment projections from Aurora.
- Enforce tenant RLS, expected aggregate version and idempotency key uniqueness.
- Never mutate a projection before the authoritative event transaction commits.
- Add deterministic replay tests rebuilding all projections from events.
- Add concurrent writer tests proving exactly one expected-version mutation wins.

Acceptance:

- No JSON, SQLite or process-local authoritative state in the durable composition.
- Duplicate idempotency keys return the original result.
- Stale mutations return a typed conflict without losing operator input.
- Restart/replay yields byte-equivalent candidate and decision projections.

### C2. MSK job transport and resilient consumers

Owned files:

- `state/msk_consumer.py` (new)
- `deployment/solver_consumer.py` (new)
- `deployment/k8s/solver-consumers.yaml` (new)
- `tests/test_msk_consumers.py` (new)

Deliver:

- IAM/TLS consumer with manual offset commits after projection/job transaction.
- Partition keys: tenant + region + resource aggregate.
- Deduplication through `consumed_event`; durable checkpoints in Aurora.
- Retry topics and dead-letter events containing schema, reason and correlation IDs.
- Graceful drain and in-flight handoff on SIGTERM.
- Tier-specific queue lag metrics usable by KEDA.

Acceptance:

- Crash before commit reprocesses safely; crash after commit does not duplicate work.
- Poison events enter DLQ without stopping the partition.
- Rebalance cannot lose or double-apply an accepted solver result.

### C3. Carrier adapter SDK

Owned files:

- `integrations/adapters/base.py` (new)
- `integrations/adapters/schedule.py` (new)
- `integrations/adapters/crew.py` (new)
- `integrations/adapters/aircraft.py` (new)
- `integrations/adapters/aodb.py` (new)
- `integrations/adapters/passenger.py` (new)
- `tests/adapters/` (new)

Deliver:

- Canonical read and write interfaces without vendor-specific assumptions.
- Contract-version negotiation, schema validation, cursor persistence and backoff.
- Circuit breaker, DLQ, reconciliation and source freshness telemetry.
- Field allowlists and PII redaction before logs/events.
- Recorded synthetic contract fixtures for ACK, NACK, timeout and out-of-order cases.

Acceptance:

- Adapters cannot publish unless a deployment command is signed, approved and current.
- Every source value records source timestamp, ingestion timestamp, version and provenance.
- Data Health blocks solving/deployment according to required-source policy.

### C4. Deployment orchestration persistence

Owned files:

- `deployment/durable_commands.py` (new)
- `state/deployment_repository.py` (new)
- `tests/test_durable_deployment_orchestration.py` (new)

Deliver:

- Persist command creation, publication, ACK/NACK/timeout and reconciliation.
- Per-resource idempotency and target-system reference.
- Retry only eligible commands; compensation only where technically supported.
- Irreversible actions require a new recovery plan, never a fake rollback.

Acceptance:

- Partial deployment can never transition to complete without required ACKs.
- Process restart during publication resumes safely.
- Reconciliation drift reopens the deployment and alerts operations.

### C5. Airline-grade scheduler frontend and dashboard

Claude owns the frontend implementation lane:

- `deployment/frontend/src/**`
- `deployment/frontend/package.json`
- `deployment/frontend/pnpm-lock.yaml`
- frontend component, accessibility and browser tests

Claude must not change backend response semantics. When a contract is missing,
document the exact requested schema in `docs/frontend-contract-requests.md` and
use an explicitly labelled unavailable state until Codex implements it.

Deliver:

- Audit the running dashboard at 1280×800, 1440×900 and 1920×1080 first.
- Simplify navigation and information hierarchy for a crew scheduler.
- Complete Overview, Data Health, Disruptions, Crew Recovery, Planned Routes,
  Tier 1/2/3, Decisions, Deployment and Audit as dedicated workspaces.
- Keep Planned Routes interactive and show every selected flight/crew movement.
- Make Tier 3 accept/reject/hold/edit understandable without implying deployment.
- Show provenance, freshness, state version, rules package and authority status.
- Implement loading, empty, stale, disconnected, `409`, `422`, permission and
  partial-deployment states.
- Preserve selections, filters and unsaved decisions during navigation.
- Use a calm premium airline-enterprise visual system; remove neon, decorative
  maps, glass-card walls, fake radar, gratuitous animation and tiny text.
- Meet WCAG 2.2 AA, full keyboard operation, visible focus, reduced motion,
  200% zoom and no full-page scrolling at the 1440×900 target.
- Add component and browser E2E tests for the complete scheduler workflow.

Acceptance:

- A new scheduler identifies disruption, urgent crew problem, blocked aircraft,
  passenger exposure, current tier and pending intervention within five seconds.
- No UI value invents legality, solver convergence, freshness or deployment ACK.
- Illegal candidates have no approval action.
- Partial deployment is never styled or announced as complete.
- Planned routes are backend-driven and interactive for every India fixture.
- Zero console errors and no horizontal clipping at required resolutions.

## Codex lane — control plane, safety and product integration

Codex retains ownership of:

- `deployment/production_api.py`
- `deployment/runtime_config.py`
- `deployment/authorization.py`
- `deployment/release_gate.py`
- frontend API contracts and final integration review (Claude owns implementation files)
- `rules/**`
- `solvers/**`
- `chaos/**`
- `.github/workflows/**`
- `infrastructure/terraform/**`

### X1. Durable composition activation

- Define the recovery-store protocol and inject Claude C1 implementation.
- Make readiness test Aurora, MSK, validation and required adapters.
- Keep production startup fail-closed until all dependencies are ready.
- Disable demo login and synthetic endpoints in production-shaped modes.

### X2. Rules completion and evidence UX

- Extend the DGCA/operator rule model only from approved requirements.
- Add cumulative duty/flight time, acclimatization, WOCL, standby, split duty,
  augmentation, cabin complement, licence/medical/recency and immigration hooks.
- Render exact inputs, arithmetic, rule reference and package version in UI.
- Keep certification state external and signed; code cannot self-certify.

### X3. Integrated candidate feasibility

- Combine crew, aircraft, airport and passenger holds into one candidate saga.
- Reject expired inventory, impossible movement and stale state.
- Persist rejected alternatives and residual risks.
- Ensure Tier 2 never replaces a better/current legal Tier 1 incumbent.

### X4. Scheduler product contract and QA support

- Implement missing backend contracts requested by Claude C5.
- Review all operator actions for RBAC, concurrency and legality invariants.
- Run browser, contract, accessibility and safety acceptance before merging.

### X5. Platform, observability and certification gates

- Finish OTel traces across API, rules, solver, events and adapters.
- Add dashboards/alarms for lag, incumbent latency, rejection and reconciliation.
- Validate Terraform, Kubernetes policies, restore procedure and regional failover.
- Expand CI with browser E2E, axe, SAST/SCA, SBOM, signature and replay gates.

## Integration sequence

1. Claude C1 → Codex X1: durable read/write store and composition activation.
2. Claude C2 → Codex X5: job transport, lag metrics and autoscaling verification.
3. Claude C3 → Codex X3: adapter contracts and joint feasibility.
4. Claude C4 + C5 → Codex X4: deployment state and complete scheduler UI.
5. Codex X2 and X5 continue in parallel without touching Claude-owned frontend files.

Each integration merge must run:

```bash
python -m compileall -q core data deployment integrations passengers predictive rules solvers state chaos
python -m pytest -q
cd deployment/frontend
pnpm install --frozen-lockfile
pnpm test
pnpm build
```

## Non-negotiable release gates

- No illegal plan is selectable for deployment.
- No carrier write without fresh authoritative inputs, holds and joint feasibility.
- Scheduler proposes, duty manager approves, authorized controller deploys.
- Recent MFA is required for approval and deployment in production.
- No complete deployment state without every required resource acknowledgement.
- No production claim without signed rules, security, load, DR, shadow and operational evidence.
- Synthetic data is always visibly labelled and cannot enable carrier publishing.

## External dependencies neither agent can fabricate

- Airline vendor API specifications, credentials and network access.
- DGCA/operator/labour agreement approval and historical regulatory corpus.
- Airline IdP metadata, role mapping and MFA policy.
- AWS account, DNS, certificates, KMS keys and production change authority.
- Security assessment, penetration test and safety-board acceptance.
- Shadow-pilot operational evidence and controlled-write authorization.

These remain blockers to real airline production acceptance, not code tasks to
silently simulate.
