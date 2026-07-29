from __future__ import annotations

from passengers.engine import PassengerRecoveryEngine
from passengers.models import Passenger, PassengerItinerary, PassengerStatus


def test_recovery_engine_selects_best_legal_itinerary():
    passenger = Passenger(
        passenger_id="P1",
        pnr="ABC123",
        origin="LAX",
        destination="JFK",
        current_airport="LAX",
        cabin="business",
        frequent_flyer_tier=3,
        medical_requirements=[],
        minor=False,
        wheelchair_required=False,
    )

    engine = PassengerRecoveryEngine()
    routes = [
        {
            "segments": [{"flight_id": "AA100", "from": "LAX", "to": "DFW"}, {"flight_id": "AA200", "from": "DFW", "to": "JFK"}],
            "score": 90,
            "reason": "Fastest legal route",
        },
        {
            "segments": [{"flight_id": "AA300", "from": "LAX", "to": "ORD"}, {"flight_id": "AA400", "from": "ORD", "to": "JFK"}],
            "score": 80,
            "reason": "Alternative route",
        },
    ]

    decision = engine.recover(passenger, routes)

    assert decision.status == PassengerStatus.REBOOKED
    assert decision.itinerary is not None
    assert decision.itinerary.segments[0]["flight_id"] == "AA100"
    assert decision.priority_score >= 0


def test_recovery_engine_waitlists_when_no_legal_itinerary_exists():
    passenger = Passenger(
        passenger_id="P2",
        pnr="XYZ999",
        origin="LAX",
        destination="JFK",
        current_airport="LAX",
        cabin="economy",
        frequent_flyer_tier=0,
        minor=True,
        wheelchair_required=False,
    )

    engine = PassengerRecoveryEngine()
    routes = [
        {
            "segments": [{"flight_id": "AA999", "from": "LAX", "to": "JFK", "minor_restricted": True}],
            "score": 10,
            "reason": "Not allowed for minors",
        }
    ]

    decision = engine.recover(passenger, routes)

    assert decision.status == PassengerStatus.WAITLISTED
    assert decision.reason == "No legal itinerary found"
