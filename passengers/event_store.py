from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class PassengerEvent:
    event_type: str
    passenger_id: str
    timestamp: datetime
    payload: Dict[str, object] = field(default_factory=dict)


class PassengerEventStore:
    """Simple append-only in-memory event store for passenger recovery."""

    def __init__(self) -> None:
        self._events: List[PassengerEvent] = []

    def append(self, event: PassengerEvent) -> None:
        self._events.append(event)

    def list_events(self, passenger_id: str | None = None) -> List[PassengerEvent]:
        if passenger_id is None:
            return list(self._events)
        return [e for e in self._events if e.passenger_id == passenger_id]

    def replay(self) -> List[PassengerEvent]:
        return list(self._events)
