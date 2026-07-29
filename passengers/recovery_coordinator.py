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
    status: str = "approved"


class PassengerRecoveryCoordinator:
    """Coordinate passenger recovery with crew/aircraft decisions."""

    def __init__(self, capacity_manager: Optional[CapacityManager] = None) -> None:
        self.capacity_manager = capacity_manager or CapacityManager()
        self.engine = PassengerRecoveryEngine()
        self.legacy_coordinator = RecoveryCoordinator()

    def coordinate(self, passengers: List[Passenger], candidate_routes: Dict[str, List[dict]], crew_proposal: Dict[str, Any], aircraft_state: Dict[str, Any]) -> JointRecoveryPlan:
        decisions: Dict[str, PassengerRecoveryDecision] = {}
        for passenger in passengers:
            routes = candidate_routes.get(passenger.passenger_id, [])
            decision = self.engine.recover(passenger, routes)
            decisions[passenger.passenger_id] = decision
            if decision.status == PassengerStatus.REBOOKED and decision.itinerary:
                for segment in decision.itinerary.segments:
                    flight_id = segment.get("flight_id")
                    if flight_id and self.capacity_manager.flights.get(flight_id):
                        self.capacity_manager.apply_seat_reserved(flight_id, passenger.cabin)

        passenger_plan = {
            passenger_id: {
                "status": decision.status.value,
                "reason": decision.reason,
                "priority_score": decision.priority_score,
            }
            for passenger_id, decision in decisions.items()
        }

        approved_plan = self.legacy_coordinator.evaluate_proposals(
            crew_proposal=crew_proposal,
            passenger_proposal=passenger_plan,
            aircraft_state=aircraft_state,
        )
        return JointRecoveryPlan(
            crew_plan=approved_plan.get("crew_plan", {}),
            passenger_plan=passenger_plan,
            aircraft_plan=aircraft_state,
            status=approved_plan.get("status", "approved"),
        )
