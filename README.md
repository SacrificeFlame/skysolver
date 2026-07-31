# SkySolver

SkySolver is an early-stage, synthetic-data prototype for resilient airline disruption recovery. Its goal is to produce a legal partial crew-recovery plan quickly, improve that plan within a time budget, and preserve a human-assisted path when automation cannot safely resolve every flight.

The repository is **not production-ready airline software**. It does not process real carrier data, and its rules engine models only a simplified, FAR 117-style subset. Several distributed-system and optimizer components described in `architecture.md` remain design targets rather than deployed capabilities.

## Implemented prototype capabilities

- Hub-based synthetic crew and flight partitioning.
- A dedicated, independently tested crew-legality module.
- A bounded Tier 1 greedy heuristic with legal partial results.
- A Tier 2 upgrade-path scaffold with a Tier 1 warm start.
- A Tier 3 review API backed by in-memory state.
- In-memory event-sourced crew state and cross-partition reconciliation.
- Synthetic passenger-recovery examples.
- A synthetic chaos/replay harness.
- An Airline Operations Control Center dashboard focused on disruption recovery.
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

The suite covers rules, Tier 1 behavior, passenger recovery, dashboard routes, and worker result handling. Passing tests demonstrate the modeled prototype behavior only; they are not evidence of regulatory certification or production-scale recovery performance.

## Important limitations

- Tier 2 is not yet a genuine MILP/column-generation implementation.
- Tier 3 suggestion generation is simplified and uses in-memory queues.
- Pulsar, BookKeeper, Flink, and production worker queues are not connected.
- The dashboard mixes backend metrics with an explicitly synthetic scenario.
- Authentication and authorization are demo-grade.
- No license has been selected.

## Project direction

The intended direction is documented in `architecture.md`. That document describes a target architecture; when it differs from working code, `docs/implementation-status.md` is authoritative about current behavior.
