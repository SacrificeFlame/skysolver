"""
SkySolver v2 - Tier 1 fast heuristic solver.

Greedy construction + large-neighborhood-search (LNS) improvement.
Goal: produce a *legal* (FAR 117-compliant) schedule in sub-second time.
Optimality is secondary - a mediocre answer that always responds beats a
perfect one that sometimes doesn't.

Every candidate move is gated by rules.engine.validate(), so the solver can
never emit an illegal assignment. If the time budget is exhausted before all
flights are covered, the partially-covered result is returned along with the
list of uncovered flights so the caller can escalate to Tier 2 / Tier 3.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Optional

from rules.engine import (
    CrewMember,
    FlightLeg,
    Assignment,
    RulesEngine,
    validate,
)


@dataclass
class PartitionResult:
    """Outcome of solving one regional partition."""
    assignments: list[Assignment]
    uncovered: list[FlightLeg]
    elapsed_s: float
    cost: float
    complete: bool  # True if every input flight was legally covered

    @property
    def coverage(self) -> float:
        total = len(self.uncovered) + sum(
            len([leg for leg in a.flight_legs if not leg.is_deadhead])
            for a in self.assignments
        )
        if total == 0:
            return 1.0
        covered = total - len(self.uncovered)
        return covered / total


def _duty_hours(a: Assignment) -> float:
    return (a.duty_end - a.duty_start).total_seconds() / 3600.0


def _deadhead_hours(a: Assignment) -> float:
    return sum(
        (leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 3600.0
        for leg in a.flight_legs
        if leg.is_deadhead
    )


def schedule_cost(assignments: list[Assignment]) -> float:
    """Lower is better. Duty time plus a penalty on deadhead time."""
    return sum(_duty_hours(a) + 0.5 * _deadhead_hours(a) for a in assignments)


def _with_leg(a: Assignment, leg: FlightLeg) -> Assignment:
    """Return a copy of `a` with `leg` appended and duty window widened."""
    return Assignment(
        crew_id=a.crew_id,
        flight_legs=a.flight_legs + [leg],
        duty_start=min(a.duty_start, leg.scheduled_dep),
        duty_end=max(a.duty_end, leg.scheduled_arr),
    )


def _new_assignment(crew: CrewMember, leg: FlightLeg) -> Assignment:
    return Assignment(
        crew_id=crew.crew_id,
        flight_legs=[leg],
        duty_start=leg.scheduled_dep,
        duty_end=leg.scheduled_arr,
    )


def _crew_index(crew_pool: list[CrewMember]) -> dict[str, CrewMember]:
    return {c.crew_id: c for c in crew_pool}


def _greedy_construct(
    crew_pool: list[CrewMember],
    flights: list[FlightLeg],
    deadline: float,
) -> tuple[list[Assignment], list[FlightLeg]]:
    """
    Greedy insertion. Flights are processed earliest-departure-first.
    For each flight we try, in order:
      1. Extend an existing assignment whose crew is currently at the origin.
      2. Open a new assignment on an idle, qualified crew at the origin.
    A move is only taken if RulesEngine.validate returns no violations.
    """
    by_id = _crew_index(crew_pool)
    assignments: list[Assignment] = []
    # Track where each assignment's crew currently is (last destination).
    location: dict[int, str] = {}  # id(assignment) -> airport
    uncovered: list[FlightLeg] = []

    ordered = sorted(flights, key=lambda f: f.scheduled_dep)
    used_crew: set[str] = set()

    for leg in ordered:
        if time.monotonic() > deadline:
            uncovered.append(leg)
            continue

        placed = False

        # 1. Try extending an existing assignment that ends at leg.origin.
        best_idx: Optional[int] = None
        best_delta = float("inf")
        for i, a in enumerate(assignments):
            if location.get(id(a)) != leg.origin:
                continue
            crew = by_id[a.crew_id]
            candidate = _with_leg(a, leg)
            if validate(crew, candidate):
                continue  # violations -> skip
            delta = _duty_hours(candidate) - _duty_hours(a)
            if delta < best_delta:
                best_delta = delta
                best_idx = i

        if best_idx is not None:
            a = assignments[best_idx]
            crew = by_id[a.crew_id]
            assignments[best_idx] = _with_leg(a, leg)
            location[id(assignments[best_idx])] = leg.destination
            placed = True

        # 2. Otherwise open a new assignment on a fresh qualified crew.
        if not placed:
            for crew in crew_pool:
                if crew.crew_id in used_crew:
                    continue
                if crew.current_location and crew.current_location != leg.origin:
                    continue
                cand = _new_assignment(crew, leg)
                if validate(crew, cand):
                    continue  # not legal for this crew
                assignments.append(cand)
                location[id(cand)] = leg.destination
                used_crew.add(crew.crew_id)
                placed = True
                break

        if not placed:
            uncovered.append(leg)

    return assignments, uncovered


def _lns_improve(
    crew_pool: list[CrewMember],
    assignments: list[Assignment],
    deadline: float,
) -> list[Assignment]:
    """
    Lightweight local search: for each assignment try reordering its legs to
    reduce duty span, keeping only reorderings that remain legal. Bounded by
    the shared deadline so it never blows the time budget.
    """
    by_id = _crew_index(crew_pool)
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        for i, a in enumerate(assignments):
            if len(a.flight_legs) < 2:
                continue
            crew = by_id[a.crew_id]
            # Sort legs by departure - usually the lowest-span legal ordering.
            reordered = sorted(a.flight_legs, key=lambda f: f.scheduled_dep)
            if reordered == a.flight_legs:
                continue
            cand = Assignment(
                crew_id=a.crew_id,
                flight_legs=reordered,
                duty_start=min(f.scheduled_dep for f in reordered),
                duty_end=max(f.scheduled_arr for f in reordered),
            )
            if not validate(crew, cand) and _duty_hours(cand) <= _duty_hours(a):
                assignments[i] = cand
                improved = True
    return assignments


def solve_partition(
    crew_pool: list[CrewMember],
    flights: list[FlightLeg],
    time_budget_s: float = 1.0,
) -> PartitionResult:
    """
    Solve one regional partition.

    Returns a PartitionResult. `complete` is True only if every input flight
    was legally covered; otherwise `uncovered` lists the flights the caller
    must escalate to Tier 2 / Tier 3.
    """
    start = time.monotonic()
    deadline = start + time_budget_s

    assignments, uncovered = _greedy_construct(crew_pool, flights, deadline)
    assignments = _lns_improve(crew_pool, assignments, deadline)

    elapsed = time.monotonic() - start
    return PartitionResult(
        assignments=assignments,
        uncovered=uncovered,
        elapsed_s=elapsed,
        cost=schedule_cost(assignments),
        complete=(len(uncovered) == 0),
    )
