from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class PassengerStatus(str, Enum):
    ACTIVE = "active"
    REBOOKED = "rebooked"
    WAITLISTED = "waitlisted"
    HOTEL_REQUIRED = "hotel_required"
    REFUND_ELIGIBLE = "refund_eligible"
    COMPLETED = "completed"


@dataclass
class Passenger:
    passenger_id: str
    pnr: str
    origin: str
    destination: str
    current_airport: str
    current_flight_id: Optional[str] = None
    cabin: str = "economy"
    frequent_flyer_tier: int = 0
    special_services: List[str] = field(default_factory=list)
    travel_group_id: Optional[str] = None
    connection_info: Optional[str] = None
    visa_restrictions: List[str] = field(default_factory=list)
    wheelchair_required: bool = False
    minor: bool = False
    medical_requirements: List[str] = field(default_factory=list)
    checked_bags: int = 0
    delay_tolerance_hours: int = 6
    compensation_status: str = "none"
    hotel_status: str = "none"
    meal_voucher_status: str = "none"
    latest_event_timestamp: Optional[datetime] = None
    recovery_status: PassengerStatus = PassengerStatus.ACTIVE


@dataclass
class PassengerItinerary:
    passenger_id: str
    segments: List[dict]
    score: float = 0.0
    reason: str = ""


@dataclass
class PassengerRecoveryDecision:
    passenger_id: str
    status: PassengerStatus
    itinerary: Optional[PassengerItinerary] = None
    reason: str = ""
    priority_score: float = 0.0
