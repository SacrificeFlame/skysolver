"""
Synthetic data generator for Tier 1 solver tests.

Produces realistic-ish crew pools and flight legs matching the scale
mentioned in the brief: thousands of crew, hundreds of aircraft/legs.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Iterator

from rules.engine import CrewMember, FlightLeg, Qualification


HUBS = ["DEL", "BOM", "BLR", "HYD", "MAA", "CCU", "AMD", "COK", "GOI", "PNQ"]
AIRCRAFT = ["B737", "A320", "B777", "A321", "B787"]


def _rand_time(base: datetime, days: int, hour_range: tuple[int, int]) -> datetime:
    day = base + timedelta(days=random.randint(0, days))
    hour = random.randint(hour_range[0], hour_range[1])
    minute = random.choice([0, 15, 30, 45])
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def generate_crew_pool(
    n: int,
    base: datetime,
    seed: int = 42,
) -> list[CrewMember]:
    """Create `n` crew members with random bases and qualifications."""
    random.seed(seed)
    crew: list[CrewMember] = []
    for i in range(n):
        base_hub = random.choice(HUBS)
        qual_count = random.randint(1, 3)
        quals = {Qualification[random.choice(AIRCRAFT)] for _ in range(qual_count)}
        # Add night / wx / etops randomly
        if random.random() < 0.3:
            quals.add(Qualification.NIGHT_FLYING)
        if random.random() < 0.2:
            quals.add(Qualification.ICU_WX)
        if random.random() < 0.1:
            quals.add(Qualification.ETOPS)

        rest_end = base - timedelta(hours=random.randint(10, 14))
        crew.append(
            CrewMember(
                crew_id=f"C{i:05d}",
                base_hub=base_hub,
                qualifications=quals,
                duty_clock_start=None,
                current_location=base_hub if random.random() < 0.8 else random.choice(HUBS),
                last_rest_end=rest_end,
            )
        )
    return crew


def generate_flight_legs(
    n: int,
    base: datetime,
    seed: int = 123,
) -> list[FlightLeg]:
    """Create `n` flight legs across the hub network."""
    random.seed(seed)
    legs: list[FlightLeg] = []
    for i in range(n):
        origin = random.choice(HUBS)
        dest = random.choice([h for h in HUBS if h != origin])
        ac = random.choice(AIRCRAFT)
        dep = _rand_time(base, 3, (6, 22))
        # block time 1-6 hours
        block = timedelta(hours=random.randint(1, 6), minutes=random.choice([0, 15, 30, 45]))
        arr = dep + block
        is_dh = random.random() < 0.1  # 10% deadhead positioning flights
        legs.append(
            FlightLeg(
                flight_id=f"FL{i:06d}",
                origin=origin,
                destination=dest,
                scheduled_dep=dep,
                scheduled_arr=arr,
                aircraft_type=ac,
                is_deadhead=is_dh,
            )
        )
    return legs


def partition_by_hub(
    crew: list[CrewMember],
    flights: list[FlightLeg],
) -> dict[str, tuple[list[CrewMember], list[FlightLeg]]]:
    """
    Very simple partitioning: group by crew base_hub and flight origin.
    A real implementation would use the more sophisticated cross-hub
    reconciliation described in the architecture doc.
    """
    parts: dict[str, tuple[list[CrewMember], list[FlightLeg]]] = {}
    for h in HUBS:
        part_crew = [c for c in crew if c.base_hub == h]
        part_flights = [f for f in flights if f.origin == h]
        if part_crew or part_flights:
            parts[h] = (part_crew, part_flights)
    return parts


if __name__ == "__main__":
    import time
    from solvers.tier1 import solve_partition

    base = datetime(2024, 1, 15, 0, 0, 0)
    crew = generate_crew_pool(2000, base)
    flights = generate_flight_legs(800, base)
    partitions = partition_by_hub(crew, flights)

    total_covered = 0
    total_flights = 0
    for hub, (pc, pf) in partitions.items():
        t0 = time.monotonic()
        res = solve_partition(pc, pf, time_budget_s=0.5)
        dt = time.monotonic() - t0
        covered = sum(len([l for l in a.flight_legs if not l.is_deadhead]) for a in res.assignments)
        total_covered += covered
        total_flights += len(pf)
        print(f"  {hub}: {covered}/{len(pf)} covered in {dt*1000:.0f}ms "
              f"({len(res.assignments)} assignments, {len(res.uncovered)} uncovered)")

    print(f"\nOverall coverage: {total_covered}/{total_flights} "
          f"({100*total_covered/max(total_flights,1):.1f}%)")
