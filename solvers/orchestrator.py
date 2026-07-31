"""Tiered recovery orchestration with a legal incumbent and human fallback."""

from __future__ import annotations

import time

from core.domain import RecoveryOutcome, RecoveryTier
from solvers.tier1 import solve_partition as tier1_solve
from solvers.tier2 import solve_partition as tier2_solve


def solve_recovery(partition_id, crew_pool, flights, tier1_budget_s=0.75, tier2_budget_s=5.0):
    """Return the best available legal result without a binary failure mode.

    Tier 1 always establishes the incumbent. Tier 2 receives that incumbent
    and may upgrade it. Any remaining uncovered flights are explicitly routed
    to Tier 3 rather than disappearing into an empty result.
    """
    started = time.monotonic()
    incumbent = tier1_solve(crew_pool, flights, tier1_budget_s)
    if incumbent.complete:
        return RecoveryOutcome(partition_id, RecoveryTier.HEURISTIC, incumbent.assignments, [], time.monotonic() - started, True, "legal heuristic completed")

    assignments, uncovered, _, converged = tier2_solve(
        crew_pool, flights, tier2_budget_s, tier1_initial=incumbent.assignments
    )
    if converged or len(uncovered) < len(incumbent.uncovered):
        tier = RecoveryTier.OPTIMIZER if converged else RecoveryTier.HUMAN_ASSIST
        reason = "optimizer completed" if converged else "optimizer improved incumbent; review remaining flights"
        return RecoveryOutcome(partition_id, tier, assignments, uncovered, time.monotonic() - started, converged, reason)
    return RecoveryOutcome(partition_id, RecoveryTier.HUMAN_ASSIST, incumbent.assignments, incumbent.uncovered, time.monotonic() - started, False, "automated time boxes exhausted; scheduler review required")
