from typing import Dict, Any, Optional

class RecoveryCoordinator:
    """Arbitrator between Crew Recovery Engine and Passenger Recovery Engine."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {
            "strict_gating": False,
            "passenger_delay_penalty": 10.0,
            "crew_disruption_penalty": 50.0,
        }

    def evaluate_proposals(self, crew_proposal: Dict[str, Any], passenger_proposal: Dict[str, Any], aircraft_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receives proposals from Crew and Passenger engines.
        Computes the global benefit to approve a final disruption plan.
        """
        # If one engine wants to cancel a flight and another wants to preserve it,
        # we compute a joint cost function.
        
        # Mock logic
        approved_plan = {
            "status": "approved",
            "crew_plan": crew_proposal,
            "passenger_plan": passenger_proposal,
            "conflicts_resolved": 0
        }
        
        return approved_plan
