# SkySolver

SkySolver is an early-stage, synthetic-data prototype for resilient airline disruption recovery. Its goal is to produce a legal partial crew-recovery plan quickly, improve that plan within a time budget, and preserve a human-assisted path when automation cannot safely resolve every flight.

The repository is **not production-ready airline software**. It does not process real carrier data, and its rules engine models only a simplified, FAR 117-style subset. Several distributed-system and optimizer components described in `architecture.md` remain design targets rather than deployed capabilities.

## Implemented prototype capabilities

- Hub-based synthetic crew and flight partitioning.
- A dedicated, independently tested crew-legality module.
- A bounded Tier 1 greedy heuristic with legal partial results.
- A Tier 2 upgrade-path scaffold with a Tier 1 warm start.
- A Tier 3 review API with a durable scheduler decision ledger.
- In-memory event-sourced crew state and cross-partition reconciliation.
- Synthetic passenger-recovery examples.
- A synthetic chaos/replay harness.
- A React + TypeScript cinematic OCC command canvas with real recovery workflow state.
- Docker, Kubernetes, KEDA, Prometheus, Railway, and worker examples.

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
python -m deployment.worker --partition DEN --tier 1 --time-budget 1
python -m deployment.worker --partition DEN --tier 2 --time-budget 1
```

These commands generate synthetic inputs and exit after processing them. Queue consumption is not implemented yet.

## Run tests

```bash
python -m pytest -q
```

The suite covers structured legality, optimistic event concurrency, tier orchestration, durable human decisions, passenger recovery, versioned dashboard routes, and worker result handling. Passing tests demonstrate modeled prototype behavior only; they are not evidence of regulatory certification or production-scale recovery performance.

## Important limitations

- Tier 2 builds legal multi-leg columns but its master selection is still a heuristic, not a genuine MILP/CP-SAT implementation.
- Tier 3 queues are process-local; scheduler decisions are persisted to SQLite but are not deployed to an external carrier schedule.
- Pulsar, BookKeeper, Flink, and production worker queues are not connected.
- The dashboard is backend-connected but uses an explicitly labelled synthetic scenario rather than carrier feeds.
- Authentication and authorization are demo-grade.
- No license has been selected.

## Project direction

The intended direction is documented in `architecture.md`. That document describes a target architecture; when it differs from working code, `docs/implementation-status.md` is authoritative about current behavior.
