from typing import Dict, Any
from state.passenger_state import Passenger

class PassengerPriorityEngine:
    """Computes a 0-100 priority score for passengers before optimization."""
    
    def __init__(self, config: Dict[str, float] = None):
        self.weights = config or {
            "tier_diamond": 30.0,
            "tier_platinum": 20.0,
            "tier_gold": 10.0,
            "cabin_first": 25.0,
            "cabin_business": 15.0,
            "medical_needs": 40.0,
            "unaccompanied_minor": 45.0,
            "military": 10.0,
            "family_group": 5.0,
            "missed_connection_time": 0.05, # per minute
        }

    def compute_score(self, passenger: Passenger) -> int:
        score = 0.0
        
        # Cabin priority
        if passenger.ticket_cabin == "first":
            score += self.weights["cabin_first"]
        elif passenger.ticket_cabin == "business":
            score += self.weights["cabin_business"]
            
        # Frequent Flyer Tier
        tier = passenger.frequent_flyer_tier.lower()
        if tier == "diamond":
            score += self.weights["tier_diamond"]
        elif tier == "platinum":
            score += self.weights["tier_platinum"]
        elif tier == "gold":
            score += self.weights["tier_gold"]
            
        # Special circumstances
        if passenger.minor_status:
            score += self.weights["unaccompanied_minor"]
        if passenger.medical_req:
            score += self.weights["medical_needs"]
        
        # Clamp to 100
        final_score = min(100, int(score))
        return final_score
