"""
SkySolver v2 - Tier 3 Human-Assist Interface

Minimal API and UI for schedulers to review/approve AI-ranked reassignments
when automated tiers exceed their time budgets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import json


class SuggestionStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


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
        }


@dataclass
class ReviewQueue:
    """Queue of suggestions for a partition."""
    partition_id: str
    suggestions: List[CrewSuggestion]
    created_at: datetime
    auto_approve_threshold: float = 0.8  # Score above which auto-approve triggers

    def get_pending(self) -> List[CrewSuggestion]:
        return [s for s in self.suggestions if s.status == SuggestionStatus.PENDING]

    def get_approved(self) -> List[CrewSuggestion]:
        return [s for s in self.suggestions if s.status in (SuggestionStatus.APPROVED, SuggestionStatus.AUTO_APPROVED)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "created_at": self.created_at.isoformat(),
            "auto_approve_threshold": self.auto_approve_threshold,
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


def generate_suggestions(
    uncovered_flights: List[Any],  # FlightLeg from rules.engine
    crew_pool: List[Any],  # CrewMember
    partition_id: str
) -> List[CrewSuggestion]:
    """
    Generate AI suggestions for uncovered flights.

    This is a placeholder - real implementation would use ML/optimization
    to propose reassignments based on current crew state.
    """
    suggestions: List[CrewSuggestion] = []

    # For now, generate simple "assign any available qualified crew" suggestions
    suggestion_id = 0
    for flight in uncovered_flights[:20]:  # Limit suggestions
        for crew in crew_pool:
            if len(suggestions) >= 20:
                break
            suggestion_id += 1
            suggestions.append(CrewSuggestion(
                suggestion_id=f"{partition_id}_SUG{suggestion_id:04d}",
                crew_id=crew.crew_id,
                original_flight_ids=[],
                proposed_flight_ids=[flight.flight_id],
                reason=f"Crew {crew.crew_id} qualified for {flight.aircraft_type}",
                rank=0,
                legal_compliance=True,
                duty_time_cost=3.0,
                seniority_fairness=0.5,
                passenger_impact_score=0.2,
                explanation=f"Crew based at {crew.base_hub}, has {flight.aircraft_type} qualification"
            ))

    return suggestions


# ----------------------------------------------------------------------
# FASTAPI BACKEND (run with: uvicorn solvers.tier3_api:app --reload)
# ----------------------------------------------------------------------

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    from typing import List as TList

    app = FastAPI(title="SkySolver v2 - Tier 3 Human Assist API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # In-memory storage (replace with Redis/DB in production)
    queues: Dict[str, ReviewQueue] = {}

    class ApproveRequest(BaseModel):
        suggestion_ids: TList[str]
        scheduler_id: str

    class QueueResponse(BaseModel):
        partition_id: str
        suggestions: TList[dict]
        created_at: str
        pending_count: int
        approved_count: int

    @app.post("/tier3/queue/{partition_id}")
    def create_queue(
        partition_id: str,
        uncovered_flights: TList[dict],
        crew_pool: TList[dict],
        auto_approve_threshold: float = 0.8
    ) -> QueueResponse:
        """Create a new review queue for a partition."""
        from rules.engine import CrewMember, FlightLeg, Qualification
        from datetime import datetime

        # Deserialize
        crew = []
        for c in crew_pool:
            quals = {Qualification[q] for q in c.get("qualifications", [])}
            crew.append(CrewMember(
                crew_id=c["crew_id"],
                base_hub=c["base_hub"],
                qualifications=quals,
                current_location=c.get("current_location", c["base_hub"]),
                last_rest_end=datetime.fromisoformat(c["last_rest_end"]) if c.get("last_rest_end") else None
            ))

        flights = []
        for f in uncovered_flights:
            flights.append(FlightLeg(
                flight_id=f["flight_id"],
                origin=f["origin"],
                destination=f["destination"],
                scheduled_dep=datetime.fromisoformat(f["scheduled_dep"]),
                scheduled_arr=datetime.fromisoformat(f["scheduled_arr"]),
                aircraft_type=f["aircraft_type"],
                is_deadhead=f.get("is_deadhead", False)
            ))

        suggestions = generate_suggestions(flights, crew, partition_id)

        # Rank
        ranker = SuggestionRanker()
        suggestions = ranker.rank_suggestions(suggestions)

        # Auto-approve high-scoring
        for s in suggestions:
            score = ranker._compute_score(s)
            if score >= auto_approve_threshold:
                s.status = SuggestionStatus.AUTO_APPROVED

        queue = ReviewQueue(
            partition_id=partition_id,
            suggestions=suggestions,
            created_at=datetime.now(),
            auto_approve_threshold=auto_approve_threshold
        )
        queues[partition_id] = queue

        return QueueResponse(**queue.to_dict())

    @app.get("/tier3/queue/{partition_id}")
    def get_queue(partition_id: str) -> QueueResponse:
        if partition_id not in queues:
            raise HTTPException(404, "Queue not found")
        return QueueResponse(**queues[partition_id].to_dict())

    @app.post("/tier3/queue/{partition_id}/approve")
    def approve_suggestions(partition_id: str, req: ApproveRequest) -> dict:
        if partition_id not in queues:
            raise HTTPException(404, "Queue not found")

        queue = queues[partition_id]
        approved = 0
        for sid in req.suggestion_ids:
            for s in queue.suggestions:
                if s.suggestion_id == sid:
                    s.status = SuggestionStatus.APPROVED
                    s.approved_by = req.scheduler_id
                    s.approved_at = datetime.now()
                    approved += 1
                    break

        return {"approved": approved, "total_pending": len(queue.get_pending())}

    @app.post("/tier3/queue/{partition_id}/reject")
    def reject_suggestions(partition_id: str, req: ApproveRequest) -> dict:
        if partition_id not in queues:
            raise HTTPException(404, "Queue not found")

        queue = queues[partition_id]
        rejected = 0
        for sid in req.suggestion_ids:
            for s in queue.suggestions:
                if s.suggestion_id == sid:
                    s.status = SuggestionStatus.REJECTED
                    rejected += 1
                    break

        return {"rejected": rejected, "total_pending": len(queue.get_pending())}

    @app.post("/tier3/queue/{partition_id}/auto_approve")
    def auto_approve_all(partition_id: str, scheduler_id: str) -> dict:
        if partition_id not in queues:
            raise HTTPException(404, "Queue not found")

        queue = queues[partition_id]
        for s in queue.get_pending():
            s.status = SuggestionStatus.AUTO_APPROVED
            s.approved_by = scheduler_id
            s.approved_at = datetime.now()

        return {"auto_approved": len(queue.get_approved())}

    @app.get("/tier3/health")
    def health():
        return {"status": "healthy", "queues": len(queues)}

except ImportError:
    # FastAPI not installed - API unavailable
    app = None