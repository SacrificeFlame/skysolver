from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class FlightEdge:
    flight_id: str
    origin: str
    destination: str
    cabin: str = "economy"
    score: float = 0.0


class ItineraryGenerator:
    """Generate a small set of candidate itineraries for a disrupted passenger."""

    def __init__(self, graph: Optional[Dict[str, List[FlightEdge]]] = None) -> None:
        self.graph = graph or {}

    def generate(self, origin: str, destination: str, max_options: int = 3) -> List[dict]:
        options: List[dict] = []
        if origin not in self.graph:
            return options

        for edge in self.graph[origin][:max_options]:
            if edge.destination == destination:
                options.append({
                    "segments": [{"flight_id": edge.flight_id, "from": edge.origin, "to": edge.destination}],
                    "score": edge.score,
                    "reason": "Direct routing",
                })
            else:
                for next_edge in self.graph.get(edge.destination, [])[:max_options]:
                    if next_edge.destination == destination:
                        options.append({
                            "segments": [
                                {"flight_id": edge.flight_id, "from": edge.origin, "to": edge.destination},
                                {"flight_id": next_edge.flight_id, "from": next_edge.origin, "to": next_edge.destination},
                            ],
                            "score": edge.score + next_edge.score,
                            "reason": "Two-leg routing",
                        })

        return options[:max_options]
