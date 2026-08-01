"""
Tier 1 Heuristic Solver - Unit Tests

Tests verify the fast heuristic produces legal, sub-second solutions
by gating all moves through the rules engine.
"""

import pytest
import time
from datetime import datetime, timedelta

from rules.engine import CrewMember, FlightLeg, Assignment, Qualification, validate
from solvers.tier1 import solve_partition, schedule_cost


class TestTier1BasicCoverage:
    """Tier 1 must cover flights with legal assignments."""

    def test_covers_simple_flight(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737},
                         current_location="DFW", last_rest_end=datetime(2023, 12, 31, 20))
        flights = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8),
                            datetime(2024, 1, 1, 11), "B737")]
        res = solve_partition([crew], flights, time_budget_s=1.0)
        assert res.complete
        assert len(res.assignments) == 1
        # Verify assignment is legal
        assert validate(crew, res.assignments[0]) == []

    def test_sub_second_performance(self):
        """Tier 1 must complete within 1 second for realistic partition."""
        from data.generate import generate_crew_pool, generate_flight_legs, partition_by_hub

        base = datetime(2024, 1, 15)
        crew = generate_crew_pool(50, base)
        flights = generate_flight_legs(20, base)
        partitions = partition_by_hub(crew, flights)

        for hub, (pc, pf) in partitions.items():
            if pf:
                start = time.monotonic()
                res = solve_partition(pc, pf, 1.0)
                elapsed = time.monotonic() - start
                assert elapsed < 1.0, f"Tier 1 exceeded 1s in {hub}: {elapsed:.3f}s"


class TestTier1Legality:
    """All assignments returned by Tier 1 must pass the configured legality profile."""

    def test_all_assignments_legal(self):
        from data.generate import generate_crew_pool, generate_flight_legs, partition_by_hub

        base = datetime(2024, 1, 15)
        crew = generate_crew_pool(100, base)
        flights = generate_flight_legs(40, base)
        partitions = partition_by_hub(crew, flights)
        by_id = {c.crew_id: c for c in crew}

        for hub, (pc, pf) in partitions.items():
            res = solve_partition(pc, pf, time_budget_s=1.0)
            for a in res.assignments:
                c = by_id[a.crew_id]
                violations = validate(c, a)
                assert violations == [], f"Illegal assignment in {hub}: {violations}"


class TestTier1GracefulDegradation:
    """Tier 1 must return partial results when time-boxed or under-resourced."""

    def test_returns_uncovered_when_insufficient_crew(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737},
                         current_location="DFW", last_rest_end=datetime(2023, 12, 31, 20))
        flights = [
            FlightLeg(f"FL{i}", "DFW", "LAX",
                      datetime(2024, 1, 1 + i // 10, 8 + (i % 8)),
                      datetime(2024, 1, 1 + i // 10, 11 + (i % 8)), "B737")
            for i in range(50)
        ]
        res = solve_partition([crew], flights, time_budget_s=0.1)
        assert not res.complete  # Single crew cannot cover 50 flights
        assert len(res.uncovered) > 0

    def test_never_emits_illegal_assignment(self):
        """Even under time pressure, Tier 1 must never return illegal assignments."""
        crew = CrewMember("C001", "DFW", {Qualification.B737},
                         current_location="DFW", last_rest_end=datetime(2023, 12, 31, 20))
        # Flight requires B777, crew only has B737
        flights = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8),
                           datetime(2024, 1, 1, 11), "B777")]
        res = solve_partition([crew], flights, time_budget_s=0.5)
        assert len(res.assignments) == 0  # Crew cannot be assigned to B777 flight


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
