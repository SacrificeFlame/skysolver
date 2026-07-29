# SkySolver

SkySolver is a prototype resilient crew rescheduling engine designed around graceful degradation under disruption rather than hard failure.

## Architecture highlights

- Regional partitioning by hub/region
- Tiered solving: Tier 1 heuristic, Tier 2 optimizer, Tier 3 human-assist
- Event-sourced crew state with cross-partition reconciliation
- Replay harness and observability dashboard for chaos testing
- Containerized worker deployment with autoscaling

## Key modules

- rules/engine.py: FAR 117-style legality checks
- solvers/tier1.py: fast legal heuristic solver
- solvers/tier2.py: time-boxed optimizer upgrade path
- solvers/tier3_api.py: scheduler review queue and approval endpoints
- state/event_store.py: append-only crew state and reconciliation
- deployment/dashboard.py: observability dashboard
- chaos/replay.py: Elliott-scale SLA test harness

## Running tests

```bash
pytest -q
```

## Notes

This repository is a prototype and uses synthetic data. Several production-grade components are intentionally simplified for clarity and testability.
