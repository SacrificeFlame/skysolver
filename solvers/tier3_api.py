"""Tier 3 human-assist domain service.

Suggestions are legal options for explicit scheduler review. This module does
not expose an unauthenticated side API and never auto-approves an operational
decision. The canonical production API owns identity, concurrency and audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import json
import sqlite3
import threading
import os
import uuid


class SuggestionStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    HELD = "held"
    SUPERSEDED = "superseded"


@dataclass
class CrewSuggestion:
    """A single AI-suggested reassignment for a crew member."""
    suggestion_id: str
    crew_id: str
    original_flight_ids: List[str]
    proposed_flight_ids: List[str]
    reason: str
    rank: int  # 1 = best
    legal_compliance: bool
    duty_time_cost: float
    seniority_fairness: float  # 0-1, higher = more fair
    passenger_impact_score: float  # 0-1, lower = less impact
    status: SuggestionStatus = SuggestionStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    explanation: str = ""
    confidence: float = 0.0
    operational_benefit: float = 0.0
    residual_risks: List[str] = field(default_factory=list)
    state_version: int = 1
    ruleset_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "crew_id": self.crew_id,
            "original_flight_ids": self.original_flight_ids,
            "proposed_flight_ids": self.proposed_flight_ids,
            "reason": self.reason,
            "rank": self.rank,
            "legal_compliance": self.legal_compliance,
            "duty_time_cost": self.duty_time_cost,
            "seniority_fairness": self.seniority_fairness,
            "passenger_impact_score": self.passenger_impact_score,
            "status": self.status.value,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "operational_benefit": self.operational_benefit,
            "residual_risks": self.residual_risks,
            "state_version": self.state_version,
            "ruleset_version": self.ruleset_version,
        }


@dataclass
class ReviewQueue:
    """Queue of suggestions for a partition."""
    partition_id: str
    suggestions: List[CrewSuggestion]
    created_at: datetime

    def get_pending(self) -> List[CrewSuggestion]:
        return [s for s in self.suggestions if s.status == SuggestionStatus.PENDING]

    def get_approved(self) -> List[CrewSuggestion]:
        return [s for s in self.suggestions if s.status == SuggestionStatus.APPROVED]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "created_at": self.created_at.isoformat(),
            "pending_count": len(self.get_pending()),
            "approved_count": len(self.get_approved()),
        }


class SuggestionRanker:
    """
    Ranks AI suggestions by:
    1. Legal compliance (hard filter - illegal suggestions ranked last)
    2. Duty-time cost (minimize disruption)
    3. Crew seniority fairness
    4. Passenger impact (gate changes, connections)
    """

    def __init__(self, seniority_data: Dict[str, int] = None):
        self.seniority = seniority_data or {}

    def rank_suggestions(
        self,
        suggestions: List[CrewSuggestion]
    ) -> List[CrewSuggestion]:
        """Sort suggestions by composite score, best first."""
        scored = []
        for s in suggestions:
            score = self._compute_score(s)
            scored.append((score, s))

        # Sort by score descending (higher = better)
        scored.sort(key=lambda x: x[0], reverse=True)

        for rank, (score, s) in enumerate(scored, 1):
            s.rank = rank

        return [s for _, s in scored]

    def _compute_score(self, s: CrewSuggestion) -> float:
        if not s.legal_compliance:
            return -1000.0  # Illegal always last

        # Weighted composite: cost (30%), fairness (20%), passenger impact (50%)
        cost_score = max(0, 1.0 - s.duty_time_cost / 20.0)  # Normalize ~20h max
        fairness_score = s.seniority_fairness
        passenger_score = 1.0 - s.passenger_impact_score

        return 0.3 * cost_score + 0.2 * fairness_score + 0.5 * passenger_score


class DecisionRepository:
    """SQLite-backed scheduler decision ledger suitable for replay/audit."""

    def __init__(self, path: str = "skysolver-decisions.db"):
        self.path = path
        self._lock = threading.RLock()
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS decisions (suggestion_id TEXT PRIMARY KEY, partition_id TEXT NOT NULL, status TEXT NOT NULL, scheduler_id TEXT, decided_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def record(self, partition_id: str, suggestion: CrewSuggestion, scheduler_id: str | None) -> None:
        with self._lock, sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR REPLACE INTO decisions VALUES (?, ?, ?, ?, ?, ?)",
                (suggestion.suggestion_id, partition_id, suggestion.status.value, scheduler_id, datetime.now().isoformat(), json.dumps(suggestion.to_dict())),
            )

    def list(self, partition_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM decisions WHERE partition_id=? ORDER BY decided_at", (partition_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]


def generate_suggestions(
    uncovered_flights: List[Any],  # FlightLeg from rules.engine
    crew_pool: List[Any],  # CrewMember
    partition_id: str,
    state_version: int = 1,
) -> List[CrewSuggestion]:
    """
    Generate independently legality-gated single-duty recovery options.

    Pagination belongs at the API boundary; generation has no hard-coded batch
    cap. Every suggestion is stable for the same partition, state and resources.
    """
    suggestions: List[CrewSuggestion] = []

    from rules.engine import Assignment, RulesEngine, validate

    for flight in uncovered_flights:
        for crew in crew_pool:
            assignment = Assignment(crew.crew_id, [flight], flight.scheduled_dep, flight.scheduled_arr)
            violations = validate(crew, assignment)
            if violations:
                continue
            suggestion_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"skysolver:{partition_id}:{state_version}:{flight.flight_id}:{crew.crew_id}"))
            duty_hours = (flight.scheduled_arr - flight.scheduled_dep).total_seconds() / 3600
            positioning_risk = 0.0 if crew.current_location == flight.origin else 1.0
            suggestions.append(CrewSuggestion(
                suggestion_id=f"SUG-{suggestion_id.upper()}",
                crew_id=crew.crew_id,
                original_flight_ids=[],
                proposed_flight_ids=[flight.flight_id],
                reason=f"Crew {crew.crew_id} qualified for {flight.aircraft_type}",
                rank=0,
                legal_compliance=True,
                duty_time_cost=duty_hours,
                seniority_fairness=0.5,
                passenger_impact_score=0.2,
                explanation=f"Crew is at {crew.current_location}, holds {flight.aircraft_type}, and passes the configured demo legality checks",
                confidence=max(0.0, 1.0-positioning_risk),
                operational_benefit=max(0.0, 1.0-duty_hours/20.0),
                residual_risks=["Aircraft, airport and passenger feasibility not yet evaluated"],
                state_version=state_version,
                ruleset_version=RulesEngine.RULESET_VERSION,
            ))

    return SuggestionRanker().rank_suggestions(suggestions)


# There is intentionally no standalone FastAPI application here. Tier 3 is
# exposed only by ``deployment.production_api``, which supplies authenticated
# server-derived identity, RBAC, idempotency and optimistic state versioning.
