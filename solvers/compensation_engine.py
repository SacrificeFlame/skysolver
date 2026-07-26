import datetime
from typing import List
from state.passenger_state import Passenger
from core.events_passenger import PassengerHotelAssigned, PassengerMealVoucherIssued, PassengerRefundRequested

class CompensationEngine:
    def __init__(self, config=None):
        self.config = config or {
            "meal_delay_threshold_mins": 180,
            "overnight_hotel_threshold_hours": 8
        }
        
    def evaluate_compensation(self, passenger: Passenger, delay_mins: int, overnight: bool) -> List[Any]:
        events = []
        if delay_mins > self.config["meal_delay_threshold_mins"] and passenger.meal_voucher_status == "none":
            events.append(PassengerMealVoucherIssued(
                event_id=f"evt_{passenger.passenger_id}_meal",
                pnr=passenger.pnr,
                passenger_id=passenger.passenger_id,
                timestamp=datetime.datetime.now(),
                metadata={"reason": "delay_exceeded_threshold"},
                value=25.00
            ))
            
        if overnight and passenger.hotel_status == "none":
            events.append(PassengerHotelAssigned(
                event_id=f"evt_{passenger.passenger_id}_hotel",
                pnr=passenger.pnr,
                passenger_id=passenger.passenger_id,
                timestamp=datetime.datetime.now(),
                metadata={"reason": "forced_overnight"},
                hotel_name="Synthetic Airport Hotel",
                check_in_time=datetime.datetime.now()
            ))
            
        return events
