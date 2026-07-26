from typing import List, Dict, Any
from state.passenger_state import Passenger

class PassengerRulesEngine:
    """Independent rules module for passenger legality."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {
            "max_overnight_layovers": 1,
            "min_connection_time_mins": 30,
            "max_travel_time_hours": 24,
        }

    def is_valid_routing(self, passenger: Passenger, itinerary: List[Dict[str, Any]]) -> bool:
        """Check if a generated itinerary is legal."""
        if not itinerary:
            return False
            
        total_time = 0
        overnight_layovers = 0
        
        for i in range(len(itinerary) - 1):
            leg1 = itinerary[i]
            leg2 = itinerary[i+1]
            
            # Simplified connection check
            conn_time = (leg2['departure_time'] - leg1['arrival_time']).total_seconds() / 60
            if conn_time < self.config["min_connection_time_mins"]:
                return False
                
            if conn_time > 8 * 60: # 8 hours
                overnight_layovers += 1
                
        if overnight_layovers > self.config["max_overnight_layovers"]:
            return False
            
        return True

    def check_visa_compatibility(self, passenger: Passenger, itinerary: List[Dict[str, Any]]) -> bool:
        # Check transit rules
        return True

    def is_special_assistance_compatible(self, passenger: Passenger, itinerary: List[Dict[str, Any]]) -> bool:
        # Check wheelchair or minor restrictions on flights
        return True
