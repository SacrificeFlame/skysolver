"""Joint resource-feasibility gate for recovery candidates.

The coordinator does not approve a plan. It produces structured evidence used
by the independent validation and approval workflow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FeasibilityFinding:
    code: str
    resource_type: str
    resource_id: str
    message: str
    blocking: bool = True


class RecoveryCoordinator:
    REQUIRED_CREW_ROLES = {"captain", "first-officer", "cabin-crew"}

    def evaluate_proposals(self, crew_proposal: dict[str, Any], passenger_proposal: dict[str, Any],
                           aircraft_state: dict[str, Any], airport_state: dict[str, Any] | None = None) -> dict[str, Any]:
        findings: list[FeasibilityFinding] = []
        airport_state = airport_state or {}
        crew_by_flight = {item["flight_id"]: item for item in crew_proposal.get("assignments", [])}
        passenger_by_flight = {item["flight_id"]: item for item in passenger_proposal.get("actions", [])}
        all_flights = sorted(set(crew_by_flight) | set(passenger_by_flight) | set(aircraft_state))

        for flight_id in all_flights:
            crew = crew_by_flight.get(flight_id)
            if crew is None:
                findings.append(FeasibilityFinding("CREW_ASSIGNMENT_MISSING", "flight", flight_id, "No crew assignment exists"))
            else:
                if not crew.get("legal", False):
                    findings.append(FeasibilityFinding("CREW_ILLEGAL", "crew", flight_id, "Crew assignment has no valid legality certificate"))
                roles = set(crew.get("roles", []))
                missing_roles = self.REQUIRED_CREW_ROLES - roles
                if missing_roles:
                    findings.append(FeasibilityFinding("CREW_COMPLEMENT_INCOMPLETE", "crew", flight_id, f"Missing roles: {', '.join(sorted(missing_roles))}"))
                if not crew.get("positioning_feasible", False):
                    findings.append(FeasibilityFinding("CREW_POSITIONING_IMPOSSIBLE", "crew", flight_id, "Crew cannot reach report point in time"))

            aircraft = aircraft_state.get(flight_id)
            if aircraft is None:
                findings.append(FeasibilityFinding("AIRCRAFT_ASSIGNMENT_MISSING", "aircraft", flight_id, "No aircraft assignment exists"))
            else:
                for field, code, message in [
                    ("available", "AIRCRAFT_UNAVAILABLE", "Aircraft is unavailable"),
                    ("compatible", "AIRCRAFT_INCOMPATIBLE", "Aircraft subtype or cabin is incompatible"),
                    ("maintenance_clear", "MAINTENANCE_RESTRICTION", "MEL/CDL or maintenance restriction blocks operation"),
                    ("turn_feasible", "TURN_TIME_INFEASIBLE", "Required turn and servicing time is unavailable"),
                ]:
                    if not aircraft.get(field, False):
                        findings.append(FeasibilityFinding(code, "aircraft", str(aircraft.get("tail", flight_id)), message))

            passenger = passenger_by_flight.get(flight_id)
            if passenger:
                if passenger.get("seats_required", 0) > passenger.get("seats_available", 0):
                    findings.append(FeasibilityFinding("PASSENGER_INVENTORY_SHORTFALL", "passenger", flight_id, "Confirmed seat inventory is insufficient"))
                for field, code, message in [
                    ("mct_feasible", "MCT_VIOLATION", "Minimum connection time is not met"),
                    ("party_integrity", "PNR_PARTY_SPLIT", "Passenger party integrity is not preserved"),
                    ("special_services_feasible", "SSR_UNSUPPORTED", "Required special service cannot be fulfilled"),
                    ("baggage_feasible", "BAGGAGE_CONNECTION_INFEASIBLE", "Baggage movement is not feasible"),
                ]:
                    if not passenger.get(field, False):
                        findings.append(FeasibilityFinding(code, "passenger", flight_id, message))

            airport = airport_state.get(flight_id)
            if airport:
                for field, code, message in [
                    ("gate_compatible", "GATE_INCOMPATIBLE", "Gate is incompatible or occupied"),
                    ("slot_valid", "SLOT_UNAVAILABLE", "Required airport slot is unavailable"),
                    ("curfew_clear", "CURFEW_VIOLATION", "Operation violates an airport curfew"),
                    ("ground_resources_available", "GROUND_RESOURCE_SHORTFALL", "Required ground resources are unavailable"),
                ]:
                    if not airport.get(field, False):
                        findings.append(FeasibilityFinding(code, "airport", flight_id, message))

        return {
            "status": "feasible" if not findings else "not_feasible",
            "deployable": not findings,
            "flights_evaluated": len(all_flights),
            "findings": [asdict(item) for item in findings],
            "evidence": {
                "crew_assignments": len(crew_by_flight),
                "aircraft_assignments": len(aircraft_state),
                "passenger_actions": len(passenger_by_flight),
                "airport_assignments": len(airport_state),
            },
        }
