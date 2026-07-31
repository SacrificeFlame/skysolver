from datetime import datetime

from data.generate import generate_crew_pool, generate_flight_legs
from deployment.worker import solve_partition_request


def test_explicit_tier2_request_returns_a_complete_result_contract():
    baseline = datetime(2024, 1, 15)
    crew = generate_crew_pool(40, baseline, seed=11)
    flights = generate_flight_legs(8, baseline, seed=12)

    result = solve_partition_request(
        "TEST",
        crew,
        flights,
        tier=2,
        time_budget=0.2,
    )

    assert result["partition_id"] == "TEST"
    assert result["tier_used"] in (1, 2)
    assert 0.0 <= result["coverage"] <= 1.0
    assert result["assignments"] >= 0
    assert result["uncovered"] >= 0
    assert isinstance(result["complete"], bool)
