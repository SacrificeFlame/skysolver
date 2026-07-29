from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from passengers.models import Passenger, PassengerItinerary, PassengerRecoveryDecision, PassengerStatus
from passengers.event_store import PassengerEvent, PassengerEventStore


@dataclass
class PassengerRulesEngine:
    """Independent rules engine for passenger recovery legality and policy."""

    def validate_itinerary(self, passenger: Passenger, itinerary: PassengerItinerary) -> List[str]:
        violations: List[str] = []
        if not itinerary.segments:
            violations.append("itinerary is empty")
            return violations

        if passenger.wheelchair_required and any(seg.get("requires_wheelchair") for seg in itinerary.segments if isinstance(seg, dict)):
            violations.append("wheelchair compatibility not satisfied")

        if passenger.minor and any(seg.get("minor_restricted") for seg in itinerary.segments if isinstance(seg, dict)):
            violations.append("minor restriction not satisfied")

        return violations

    def priority_score(self, passenger: Passenger) -> float:
        score = 0.0
        score += min(passenger.frequent_flyer_tier * 5, 25)
        if passenger.medical_requirements:
            score += 20
        if passenger.minor:
            score += 10
        if passenger.wheelchair_required:
            score += 15
        if passenger.cabin == "business":
            score += 10
        if passenger.cabin == "first":
            score += 15
        return min(score, 100.0)


class PassengerRecoveryEngine:
    """Tier 1 passenger recovery engine with greedy, legal itinerary selection."""

    def __init__(self, event_store: Optional[PassengerEventStore] = None) -> None:
        self.rules = PassengerRulesEngine()
        self.event_store = event_store or PassengerEventStore()

    def recover(self, passenger: Passenger, candidate_routes: List[dict]) -> PassengerRecoveryDecision:
        ranked: List[Tuple[float, PassengerItinerary]] = []
        for route in candidate_routes:
            itinerary = PassengerItinerary(
                passenger_id=passenger.passenger_id,
                segments=route.get("segments", []),
                score=route.get("score", 0.0),
                reason=route.get("reason", ""),
            )
            violations = self.rules.validate_itinerary(passenger, itinerary)
            if violations:
                continue
            ranked.append((itinerary.score, itinerary))

        if not ranked:
            self._emit(passenger.passenger_id, "PassengerWaitlisted", {"reason": "no legal itinerary"})
            return PassengerRecoveryDecision(
                passenger_id=passenger.passenger_id,
                status=PassengerStatus.WAITLISTED,
                reason="No legal itinerary found",
                priority_score=self.rules.priority_score(passenger),
            )

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_itinerary = ranked[0][1]
        self._emit(passenger.passenger_id, "PassengerRebooked", {"itinerary": best_itinerary.segments})
        return PassengerRecoveryDecision(
            passenger_id=passenger.passenger_id,
            status=PassengerStatus.REBOOKED,
            itinerary=best_itinerary,
            reason=best_itinerary.reason or "Best available itinerary",
            priority_score=self.rules.priority_score(passenger),
        )

    def _emit(self, passenger_id: str, event_type: str, payload: Dict[str, object]) -> None:
        self.event_store.append(PassengerEvent(event_type=event_type, passenger_id=passenger_id, timestamp=__import__("datetime").datetime.now(), payload=payload))
