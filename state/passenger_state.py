from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TravelGroup:
    group_id: str
    passenger_ids: List[str]
    group_type: str  # e.g., 'family', 'corporate'
    can_split: bool = False
    split_penalty: float = 0.0

@dataclass
class ConnectionInfo:
    previous_flight: str
    next_flight: str
    min_connection_time_mins: int
    layover_airport: str

@dataclass
class Passenger:
    passenger_id: str
    pnr: str
    current_airport: str
    final_destination: str
    origin: str
    current_flight: Optional[str]
    ticket_cabin: str
    frequent_flyer_tier: str
    special_service_requests: List[str]
    travel_group_id: Optional[str]
    connection_info: Optional[ConnectionInfo]
    visa_restrictions: List[str]
    wheelchair_req: bool
    minor_status: bool
    medical_req: bool
    checked_bags: int
    delay_tolerance_mins: int
    
    # State tracking
    rebooking_history: List[str] = field(default_factory=list)
    compensation_status: str = "none"
    hotel_status: str = "none"
    meal_voucher_status: str = "none"
    latest_event_ts: Optional[datetime] = None
    recovery_status: str = "nominal"

class PassengerStateStore:
    def __init__(self):
        self.passengers: Dict[str, Passenger] = {}
        self.travel_groups: Dict[str, TravelGroup] = {}
    
    def apply_event(self, event):
        # Event sourced state updates would go here
        pass
