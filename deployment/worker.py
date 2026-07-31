"""
SkySolver v2 - Worker Entry Point

Consumes partition solve requests from queue, runs tiered solving,
publishes results. Scaled horizontally via KEDA in production.
"""

from __future__ import annotations

import argparse
import time
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from typing import Optional

# In production: consume from Pulsar queue
# from pulsar import Client

from data.generate import generate_crew_pool, generate_flight_legs, partition_by_hub
from solvers.tier1 import PartitionResult, solve_partition
from solvers.tier2 import solve_partition as tier2_solve
from state.event_store import EventStore, create_crew_event, CrossPartitionReconciler


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/ready"):
            body = json.dumps({"status": "healthy", "ready": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_health_server(port: int = 8080):
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def solve_partition_request(
    partition_id: str,
    crew_pool: list,
    flights: list,
    tier: int = 1,
    time_budget: float = 1.0
) -> dict:
    """
    Solve one partition request.

    Returns result dict with assignments, coverage, tier used.
    """
    start = time.monotonic()

    if tier == 1:
        res = solve_partition(crew_pool, flights, time_budget_s=time_budget)
        tier_used = 1
        # Try Tier 2 upgrade if time allows
        if not res.complete and time_budget > 0.1:
            assignments, uncovered, elapsed, converged = tier2_solve(
                crew_pool, flights, time_budget_s=min(5.0, time_budget * 3)
            )
            if converged:
                tier_used = 2
                res = type(res)(
                    assignments=assignments,
                    uncovered=uncovered,
                    elapsed_s=elapsed,
                    cost=sum(len(a.flight_legs) for a in assignments),
                    complete=True,
                )
    else:
        # Tier 2 is an upgrade path, so always provide a legal Tier 1
        # incumbent. If the optimizer times out, the worker can still return
        # the best known legal schedule rather than an empty result.
        tier1_incumbent = solve_partition(
            crew_pool,
            flights,
            time_budget_s=min(0.1, time_budget),
        )
        assignments, uncovered, elapsed, converged = tier2_solve(
            crew_pool,
            flights,
            time_budget_s=time_budget,
            tier1_initial=tier1_incumbent.assignments,
        )
        tier_used = 2 if converged else 1
        res = PartitionResult(
            assignments=assignments,
            uncovered=uncovered,
            elapsed_s=elapsed,
            cost=sum(len(a.flight_legs) for a in assignments),
            complete=converged,
        )

    elapsed = time.monotonic() - start

    return {
        "partition_id": partition_id,
        "tier_used": tier_used,
        "assignments": len(res.assignments),
        "uncovered": len(res.uncovered),
        "coverage": res.coverage,
        "elapsed_s": elapsed,
        "complete": res.complete,
    }


def main():
    parser = argparse.ArgumentParser(description="SkySolver v2 Worker")
    parser.add_argument("--partition", default="all", help="Partition ID or 'all'")
    parser.add_argument("--tier", type=int, default=1, help="Solver tier (1 or 2)")
    parser.add_argument("--time-budget", type=float, default=1.0, help="Time budget seconds")
    args = parser.parse_args()

    start_health_server(int(os.environ.get("HEALTH_PORT", "8080")))
    print(f"Worker started for partition={args.partition}, tier={args.tier}")

    # In production: consume from Pulsar queue
    # client = Client('pulsar://localhost:6650')
    # consumer = client.subscribe('skysolver-partitions', 'worker-group')

    # For demo: generate synthetic data and solve
    baseline = datetime(2024, 1, 15)
    crew = generate_crew_pool(200, baseline)
    flights = generate_flight_legs(50, baseline)
    partitions = partition_by_hub(crew, flights)

    for hub, (pc, pf) in partitions.items():
        if args.partition != "all" and hub != args.partition:
            continue
        if not pf:
            continue

        result = solve_partition_request(hub, pc, pf, args.tier, args.time_budget)
        print(f"  {hub}: tier={result['tier_used']}, "
              f"coverage={result['coverage']:.1%}, "
              f"time={result['elapsed_s']*1000:.0f}ms")

    print("Worker idle - waiting for requests...")
    # In production: block on consumer.receive()


if __name__ == "__main__":
    main()
