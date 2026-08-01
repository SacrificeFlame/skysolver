# SkySolver

SkySolver is an early-stage, synthetic-data prototype for resilient airline disruption recovery. Its goal is to produce a legal partial crew-recovery plan quickly, improve that plan within a time budget, and preserve a human-assisted path when automation cannot safely resolve every flight.

The repository is **not production-ready airline software**. It does not process real carrier data, and its DGCA-oriented rules profile is not operator-approved or certified. Carrier publishing is disabled and production-shaped configuration fails closed unless a durable workflow composition is injected.

## Implemented prototype capabilities

- Hub-based synthetic crew and flight partitioning.
- A dedicated, independently tested crew-legality module.
- A bounded Tier 1 greedy heuristic with legal partial results.
- A restricted-master MILP Tier 2 upgrade path with a Tier 1 warm start and truthful solver telemetry.
- An authenticated, versioned Tier 3 scheduler workflow with no automatic approval.
- Aurora event/outbox repositories, MSK IAM publishing, rebuildable projections and cross-partition sagas.
- Synthetic passenger-recovery examples.
- A synthetic chaos/replay harness.
- A React + TypeScript cinematic OCC command canvas with real recovery workflow state.
- KMS/S3 Object Lock artifacts, OIDC/RBAC/MFA gates and signed release evidence.
- Terraform for EKS, Aurora, MSK, Redis, S3, KMS, Cognito federation, ALB/WAF/Route 53, backups and managed Prometheus.

See [docs/implementation-status.md](docs/implementation-status.md) for the verified maturity of each area and the current production gaps.

## Local setup

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run the dashboard

```bash
python main.py
```

The server uses the `PORT` environment variable and defaults to `8000`. The current UI is a clearly synthetic operational scenario; it is not a live airline feed.

The production frontend bundle is committed under `deployment/frontend/dist` and served at `/dashboard`. To develop or rebuild it:

```bash
cd deployment/frontend
pnpm install
pnpm run dev      # Vite with /api proxy to port 8501
pnpm run build    # production bundle served by Python
```

The command canvas connects to `/api/v1/disruptions`, `/flights`, `/recoveries`, `/audit`, and `/events`. Recovery mutations enforce state versions, legality gates, explicit validation and idempotent deployment.

## Run solver-worker demos

```bash
python -m deployment.worker --partition DEL --tier 1 --time-budget 1
python -m deployment.worker --partition DEL --tier 2 --time-budget 1
```

These commands generate synthetic inputs and exit after processing them. The transactional outbox publisher has a concrete Aurora IAM/MSK IAM runtime; the solver job-consumer runtime remains incomplete.

## Run tests

```bash
python -m pytest -q
```

The suite covers structured legality, optimistic event concurrency, tier orchestration, durable human decisions, passenger recovery, versioned dashboard routes, and worker result handling. Passing tests demonstrate modeled prototype behavior only; they are not evidence of regulatory certification or production-scale recovery performance.

## Important limitations

- Tier 2 is an actual restricted-master MILP when a configured solver is available, but it is not branch-and-price and has no certified optimality claim.
- Tier 3 is integrated into the authenticated recovery API, but real airline resource inputs are unavailable.
- Aurora/MSK adapters and projections exist; the full API-side durable workflow store and solver job consumer are not yet activated.
- The dashboard is backend-connected but uses an explicitly labelled synthetic scenario rather than carrier feeds.
- Enterprise OIDC validation, RBAC and MFA step-up paths exist, but no airline IdP is configured in this repository.
- No license has been selected.

## Project direction

The intended direction is documented in `architecture.md`. That document describes a target architecture; when it differs from working code, `docs/implementation-status.md` is authoritative about current behavior.
