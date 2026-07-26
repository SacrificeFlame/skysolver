from typing import Dict, Any
from dataclasses import dataclass

@dataclass
class FlightCapacity:
    flight_id: str
    economy_total: int
    premium_economy_total: int
    business_total: int
    first_total: int
    
    economy_booked: int = 0
    premium_economy_booked: int = 0
    business_booked: int = 0
    first_booked: int = 0

    @property
    def economy_available(self) -> int:
        return self.economy_total - self.economy_booked

    @property
    def premium_economy_available(self) -> int:
        return self.premium_economy_total - self.premium_economy_booked

    @property
    def business_available(self) -> int:
        return self.business_total - self.business_booked

    @property
    def first_available(self) -> int:
        return self.first_total - self.first_booked

class CapacityManager:
    """Event sourced dynamic seat inventory."""
    def __init__(self):
        self.flights: Dict[str, FlightCapacity] = {}

    def apply_seat_reserved(self, flight_id: str, cabin: str):
        if flight_id not in self.flights:
            return
        cap = self.flights[flight_id]
        if cabin == "economy": cap.economy_booked += 1
        elif cabin == "premium_economy": cap.premium_economy_booked += 1
        elif cabin == "business": cap.business_booked += 1
        elif cabin == "first": cap.first_booked += 1

    def apply_seat_released(self, flight_id: str, cabin: str):
        if flight_id not in self.flights:
            return
        cap = self.flights[flight_id]
        if cabin == "economy": cap.economy_booked -= 1
        elif cabin == "premium_economy": cap.premium_economy_booked -= 1
        elif cabin == "business": cap.business_booked -= 1
        elif cabin == "first": cap.first_booked -= 1
