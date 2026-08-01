from core.recovery_coordinator import RecoveryCoordinator


def legal_crew():
    return {"assignments": [{"flight_id": "AI421", "legal": True, "roles": ["captain", "first-officer", "cabin-crew"], "positioning_feasible": True}]}


def feasible_aircraft():
    return {"AI421": {"tail": "VT-EXA", "available": True, "compatible": True, "maintenance_clear": True, "turn_feasible": True}}


def feasible_passengers():
    return {"actions": [{"flight_id": "AI421", "seats_required": 12, "seats_available": 20, "mct_feasible": True, "party_integrity": True, "special_services_feasible": True, "baggage_feasible": True}]}


def feasible_airport():
    return {"AI421": {"gate_compatible": True, "slot_valid": True, "curfew_clear": True, "ground_resources_available": True}}


def test_jointly_feasible_candidate_is_deployable_but_not_auto_approved():
    result = RecoveryCoordinator().evaluate_proposals(legal_crew(), feasible_passengers(), feasible_aircraft(), feasible_airport())
    assert result["status"] == "feasible"
    assert result["deployable"] is True
    assert "approved" not in result


def test_each_resource_domain_can_block_candidate():
    crew = legal_crew(); crew["assignments"][0]["positioning_feasible"] = False
    aircraft = feasible_aircraft(); aircraft["AI421"]["maintenance_clear"] = False
    passengers = feasible_passengers(); passengers["actions"][0]["seats_available"] = 2
    airport = feasible_airport(); airport["AI421"]["curfew_clear"] = False
    result = RecoveryCoordinator().evaluate_proposals(crew, passengers, aircraft, airport)
    codes = {item["code"] for item in result["findings"]}
    assert {"CREW_POSITIONING_IMPOSSIBLE", "MAINTENANCE_RESTRICTION", "PASSENGER_INVENTORY_SHORTFALL", "CURFEW_VIOLATION"} <= codes
    assert result["deployable"] is False


def test_missing_crew_or_aircraft_is_blocking():
    result = RecoveryCoordinator().evaluate_proposals({"assignments": []}, {"actions": []}, {"AI421": feasible_aircraft()["AI421"]})
    assert any(item["code"] == "CREW_ASSIGNMENT_MISSING" for item in result["findings"])
