from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class PassengerEvent:
    event_id: str
    pnr: str
    passenger_id: str
    timestamp: datetime
    metadata: Dict[str, Any]

@dataclass
class PassengerCheckedIn(PassengerEvent):
    origin: str
    destination: str

@dataclass
class PassengerBoarded(PassengerEvent):
    flight_id: str

@dataclass
class PassengerMisconnected(PassengerEvent):
    missed_flight_id: str
    current_location: str
    reason: str

@dataclass
class PassengerRebooked(PassengerEvent):
    old_flight_id: str
    new_flight_id: str
    reason: str

@dataclass
class PassengerRefundRequested(PassengerEvent):
    amount: float

@dataclass
class PassengerVoucherIssued(PassengerEvent):
    voucher_type: str
    amount: float

@dataclass
class PassengerCancelled(PassengerEvent):
    reason: str

@dataclass
class PassengerPriorityChanged(PassengerEvent):
    old_score: int
    new_score: int
    reason: str

@dataclass
class PassengerHotelAssigned(PassengerEvent):
    hotel_name: str
    check_in_time: datetime

@dataclass
class PassengerMealVoucherIssued(PassengerEvent):
    value: float
