from datetime import datetime, timedelta

import pytest

pytest.importorskip("pyomo.environ")

from pyomo.environ import value
from rules.engine import Assignment, CrewMember, FlightLeg, Qualification
from solvers.tier2 import Column, RestrictedMasterOptimizer


def fixtures():
    start = datetime(2026, 8, 1, 8)
    flights = [
        FlightLeg("AI1", "DEL", "BOM", start, start+timedelta(hours=2), "A321"),
        FlightLeg("AI2", "DEL", "BLR", start+timedelta(hours=3), start+timedelta(hours=5), "A321"),
    ]
    crew = [CrewMember("C1", "DEL", {Qualification.A321}, current_location="DEL")]
    columns = [Column("C1", (flights[0],), 2), Column("C1", (flights[1],), 2)]
    return crew, flights, columns


def test_restricted_master_is_binary_set_partitioning_not_greedy_label():
    _, flights, columns = fixtures()
    model = RestrictedMasterOptimizer.build_model(columns, flights)
    assert len(model.cover_exactly_once) == 2
    assert len(model.one_duty_per_crew) == 1
    assert value(model.objective, exception=False) is None


def test_unavailable_solver_truthfully_retains_tier1(monkeypatch):
    crew, flights, _ = fixtures()
    incumbent = [Assignment("C1", [flights[0]], flights[0].scheduled_dep, flights[0].scheduled_arr)]
    result = RestrictedMasterOptimizer(.1, "solver-that-does-not-exist").solve(crew, flights, incumbent)
    assert result.metadata.status == "solver_unavailable"
    assert result.metadata.upgraded is False
    assert [item.flight_id for item in result.uncovered] == ["AI2"]
    assert result.assignments == incumbent
