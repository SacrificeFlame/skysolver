from __future__ import annotations

from passengers.models import Passenger, PassengerStatus
from passengers.recovery_coordinator import PassengerRecoveryCoordinator
from state.capacity_manager import CapacityManager, FlightCapacity


def test_joint_recovery_coordinator_checks_capacity_without_publishing_reservation():
    capacity_manager = CapacityManager()
    capacity_manager.flights["AA100"] = FlightCapacity(flight_id="AA100", economy_total=10, premium_economy_total=0, business_total=5, first_total=0)
    capacity_manager.flights["AA200"] = FlightCapacity(flight_id="AA200", economy_total=10, premium_economy_total=0, business_total=5, first_total=0)

    coordinator = PassengerRecoveryCoordinator(capacity_manager=capacity_manager)
    passenger = Passenger(
        passenger_id="P100",
        pnr="PNR100",
        origin="LAX",
        destination="JFK",
        current_airport="LAX",
        cabin="business",
        frequent_flyer_tier=4,
        medical_requirements=[],
        minor=False,
        wheelchair_required=False,
    )

    routes = {
        passenger.passenger_id: [
            {
                "segments": [{"flight_id": "AA100", "from": "LAX", "to": "DFW"}, {"flight_id": "AA200", "from": "DFW", "to": "JFK"}],
                "score": 95,
                "reason": "Direct-ish recovery",
            }
        ]
    }

    plan = coordinator.coordinate(
        passengers=[passenger],
        candidate_routes=routes,
        crew_proposal={"assignments": [
            {"flight_id": "AA100", "legal": True, "roles": ["captain", "first-officer", "cabin-crew"], "positioning_feasible": True},
            {"flight_id": "AA200", "legal": True, "roles": ["captain", "first-officer", "cabin-crew"], "positioning_feasible": True},
        ]},
        aircraft_state={
            "AA100": {"tail": "VT-AAA", "available": True, "compatible": True, "maintenance_clear": True, "turn_feasible": True},
            "AA200": {"tail": "VT-AAB", "available": True, "compatible": True, "maintenance_clear": True, "turn_feasible": True},
        },
    )

    assert plan.status == "feasible"
    assert plan.deployable is True
    assert plan.passenger_plan[passenger.passenger_id]["status"] == PassengerStatus.REBOOKED.value
    assert capacity_manager.flights["AA100"].business_booked == 0
