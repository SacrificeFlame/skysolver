from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from passengers.models import Passenger, PassengerRecoveryDecision, PassengerStatus
from passengers.engine import PassengerRecoveryEngine
from state.capacity_manager import CapacityManager
from core.recovery_coordinator import RecoveryCoordinator


@dataclass
class JointRecoveryPlan:
    crew_plan: Dict[str, Any]
    passenger_plan: Dict[str, Any]
    aircraft_plan: Dict[str, Any]
    status: str = "not_feasible"
    deployable: bool = False
    findings: List[Dict[str, Any]] = None


class PassengerRecoveryCoordinator:
    """Coordinate passenger recovery with crew/aircraft decisions."""

    def __init__(self, capacity_manager: Optional[CapacityManager] = None) -> None:
        self.capacity_manager = capacity_manager or CapacityManager()
        self.engine = PassengerRecoveryEngine()
        self.feasibility_coordinator = RecoveryCoordinator()

    def coordinate(self, passengers: List[Passenger], candidate_routes: Dict[str, List[dict]], crew_proposal: Dict[str, Any], aircraft_state: Dict[str, Any]) -> JointRecoveryPlan:
        decisions: Dict[str, PassengerRecoveryDecision] = {}
        for passenger in passengers:
            routes = candidate_routes.get(passenger.passenger_id, [])
            decision = self.engine.recover(passenger, routes)
            decisions[passenger.passenger_id] = decision

        passenger_plan = {
            passenger_id: {
                "status": decision.status.value,
                "reason": decision.reason,
                "priority_score": decision.priority_score,
            }
            for passenger_id, decision in decisions.items()
        }

        passenger_actions = []
        for passenger, decision in ((item, decisions[item.passenger_id]) for item in passengers):
            if decision.status != PassengerStatus.REBOOKED or not decision.itinerary:
                continue
            for segment in decision.itinerary.segments:
                flight_id = segment.get("flight_id")
                capacity = self.capacity_manager.flights.get(flight_id)
                available = 0
                if capacity:
                    total = getattr(capacity, f"{passenger.cabin}_total", 0)
                    booked = getattr(capacity, f"{passenger.cabin}_booked", 0)
                    available = total - booked
                passenger_actions.append({"flight_id": flight_id, "seats_required": 1, "seats_available": available,
                    "mct_feasible": True, "party_integrity": True, "special_services_feasible": True, "baggage_feasible": True})

        feasibility = self.feasibility_coordinator.evaluate_proposals(
            crew_proposal=crew_proposal,
            passenger_proposal={"actions": passenger_actions},
            aircraft_state=aircraft_state,
        )
        return JointRecoveryPlan(
            crew_plan=crew_proposal,
            passenger_plan=passenger_plan,
            aircraft_plan=aircraft_state,
            status=feasibility["status"],
            deployable=feasibility["deployable"],
            findings=feasibility["findings"],
        )
