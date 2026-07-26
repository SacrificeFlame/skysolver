# SkySolver v2 - Chaos/Replay SLA Report

**Generated:** 2024-07-18 (runtime)
**Test Profile:** Winter Storm Elliott Scale (1x and 3x)

---

## 1. SLA Definition

| Tier | Requirement | Threshold |
|------|-------------|-----------|
| Tier 1 | 100% of affected crew have legal solution | Within 5 minutes |
| Tier 2 | 60% of partitions converge to better solution | Within 5 minutes |
| Tier 3 | All partitions produce human-reviewable output | Within 30 seconds of trigger |

---

## 2. Current Test Results (Elliott 1x Scale)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Tier 1 Coverage | 100% | 100.0% | ✅ PASS |
| Tier 1 Solve Time | < 300s | 0.6s | ✅ PASS |
| Tier 2 Convergence | 60% | 100.0% | ✅ PASS |
| Tier 3 Output Time | < 30s | 0.000s | ✅ PASS |

**OVERALL: ✅ PASS** — `python -m chaos.replay` exits 0.

---

## 3. Architecture Compliance

| Brief Requirement | Status | Notes |
|-------------------|--------|-------|
| Regional partitioning | ✅ | `data/generate.py::partition_by_hub` splits by hub |
| Tiered solving (race-style) | ✅ | Tier 1 (greedy+LNS) → Tier 2 (column gen) → Tier 3 (human) |
| Elastic compute | ✅ (config) | K8s + KEDA autoscaler in `deployment/k8s/` |
| Event-sourced state | ✅ | `state/event_store.py` append-only + materialized view |
| Hard legality layer | ✅ | `rules/engine.py`, 16 unit tests, called by all tiers |
| Predictive pre-staging | ✅ | `predictive/prestaging.py` weather signal → worker scaling |
| Observability + chaos | ✅ | `deployment/dashboard.py` + `chaos/replay.py` |

---

## 4. Known Shortfalls / Simplifying Assumptions

1. **Tier 2 is greedy set-partitioning, not full branch-and-price.**
   The brief specified column generation with branch-and-price. The current
   `ColumnGenerationSolver` does greedy column generation + set-partitioning
   master (one crew per flight). It converges and produces *legal* solutions,
   but is not provably near-optimal. A production system would add Lagrangian
   relaxation / branch-and-price for optimality guarantees.

2. **Synthetic data only.** All crew/flight volumes are generated
   (`data/generate.py`). No real airline data is used or claimed.

3. **Cross-partition reconciliation is post-solve only.** The reconciler
   (`state/event_store.py::CrossPartitionReconciler`) emits completion events
   but does not pre-coordinated solve across partitions. At Elliott 1x scale
   with per-hub partitioning, cross-partition moves were 0 (no moves needed).

4. **Dashboard metrics are file-backed** (`.sky_metrics.json`) for the local
   demo. Production should use Prometheus (`deployment/prometheus.yml`
   provided) instead of a shared JSON file.

5. **Tier 3 suggestion ranking is heuristic.** `solvers/tier3_api.py` ranks by
   composite score (cost/fairness/passenger impact). The "why" explainer is
   placeholder text, not a true model explanation.

---

## 5. How to Run

```bash
# Unit tests (rules engine + Tier 1)
python -m pytest

# Elliott 1x SLA gate (exits 0 on pass, 1 on fail)
python -m chaos.replay

# 3x stress scale
python -c "from chaos.replay import run_elliott_3x_sla_test; print(run_elliott_3x_sla_test())"

# Observability dashboard (http://localhost:8501)
python -m deployment.dashboard

# Tier 3 human-assist API (http://localhost:8000/docs)
uvicorn solvers.tier3_api:app --reload
```

---

*Note: this report reflects the running system as of the last `chaos.replay`
execution. Numbers above are filled from that live run.*
