import time
from typing import List, Dict, Any, Tuple
from state.passenger_state import Passenger
from rules.passenger_rules import PassengerRulesEngine

class PassengerTier1Solver:
    """Fast graph search solver for immediate legal itineraries (Milliseconds)."""
    
    def __init__(self, rules_engine: PassengerRulesEngine, capacity_manager):
        self.rules_engine = rules_engine
        self.capacity = capacity_manager
        
    def generate_candidate_itineraries(self, passenger: Passenger, available_flights: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Simple greedy search for connecting flights."""
        # This is a mock implementation of a constrained A* / shortest path
        candidates = []
        origin = passenger.current_airport
        dest = passenger.final_destination
        
        # 1-stop options
        direct = [f for f in available_flights if f['origin'] == origin and f['dest'] == dest]
        if direct:
            candidates.append([direct[0]])
            
        return candidates

    def solve(self, affected_passengers: List[Passenger], network_flights: List[Dict[str, Any]]) -> Dict[str, Any]:
        start_time = time.time()
        assignments = {}
        unassigned = []
        
        for p in affected_passengers:
            candidates = self.generate_candidate_itineraries(p, network_flights)
            assigned = False
            for cand in candidates:
                if self.rules_engine.is_valid_routing(p, cand):
                    # Check capacity (simplified)
                    assignments[p.passenger_id] = cand
                    assigned = True
                    break
                    
            if not assigned:
                unassigned.append(p.passenger_id)
                
        return {
            "tier": 1,
            "solve_time_ms": int((time.time() - start_time) * 1000),
            "assignments": assignments,
            "unassigned_count": len(unassigned)
        }
