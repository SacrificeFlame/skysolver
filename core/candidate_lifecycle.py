"""Immutable recovery-candidate lifecycle and upgrade policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Protocol
import uuid

from state.immutable_artifacts import ArtifactReference


class CandidateRejected(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code=code


@dataclass(frozen=True)
class CandidateMetrics:
    legal_assignments: int
    unresolved_cases: int
    recovered_flights: int
    total_delay_minutes: int
    passenger_misconnections: int
    operational_cost_minor: int
    residual_risk_score: float
    objective_score: float


@dataclass(frozen=True)
class CandidateDraft:
    tenant_id: str
    recovery_id: str
    input_snapshot_id: str
    solver_tier: str
    solver_version: str
    ruleset_version: str
    objective_version: str
    state_version: int
    assignments: tuple[dict[str, Any], ...]
    movement_segments: tuple[dict[str, Any], ...]
    rejected_alternatives: tuple[dict[str, Any], ...]
    residual_cases: tuple[dict[str, Any], ...]
    metrics: CandidateMetrics
    legality_certificate: dict[str, Any] | None
    expires_at: datetime


@dataclass(frozen=True)
class ImmutableCandidate:
    candidate_id: str
    candidate_version: int
    content_sha256: str
    artifact: ArtifactReference
    draft: CandidateDraft
    created_at: datetime

    @property
    def legal(self) -> bool:
        certificate=self.draft.legality_certificate or {}
        return bool(certificate.get("valid")) and not certificate.get("findings")


class ArtifactWriter(Protocol):
    def put(self, *, tenant_id: str, recovery_id: str, artifact_type: str,
            artifact_id: str, value: Any) -> ArtifactReference: ...


class CandidateRepository(Protocol):
    def insert(self, candidate: ImmutableCandidate) -> None: ...


class CandidateLifecycle:
    def __init__(self, artifact_writer: ArtifactWriter, repository: CandidateRepository):
        self.artifact_writer=artifact_writer;self.repository=repository

    @staticmethod
    def _validate(draft: CandidateDraft, now: datetime) -> None:
        if draft.state_version < 1: raise CandidateRejected("invalid_state_version","Candidate state version is invalid")
        if draft.expires_at.tzinfo is None or draft.expires_at<=now:
            raise CandidateRejected("candidate_expired","Candidate expiry must be a future timezone-aware instant")
        if draft.solver_tier not in {"tier1","tier2","tier3"}:
            raise CandidateRejected("unknown_solver_tier","Candidate solver tier is unknown")
        if draft.metrics.legal_assignments != len(draft.assignments):
            raise CandidateRejected("coverage_mismatch","Legal-assignment metric does not match candidate content")

    def create(self, draft: CandidateDraft, now: datetime | None = None) -> ImmutableCandidate:
        now=now or datetime.now(timezone.utc);self._validate(draft,now)
        candidate_id=f"CAN-{uuid.uuid4().hex[:16].upper()}"
        content={"candidate_id":candidate_id,"candidate_version":1,"draft":asdict(draft),"created_at":now}
        canonical=json.dumps(content,sort_keys=True,separators=(",",":"),default=str).encode()
        digest=hashlib.sha256(canonical).hexdigest()
        reference=self.artifact_writer.put(tenant_id=draft.tenant_id,recovery_id=draft.recovery_id,
            artifact_type="candidate",artifact_id=candidate_id,value=content)
        if reference.content_sha256!=digest:
            raise CandidateRejected("artifact_digest_mismatch","Immutable artifact digest does not match candidate")
        candidate=ImmutableCandidate(candidate_id,1,digest,reference,draft,now)
        self.repository.insert(candidate)
        return candidate


@dataclass(frozen=True)
class UpgradeDecision:
    accepted: bool
    reasons: tuple[str,...]
    objective_improvement: float


def evaluate_upgrade(incumbent: ImmutableCandidate, proposed: ImmutableCandidate,
                     *, current_state_version: int, now: datetime | None = None,
                     minimum_objective_improvement: float = 0.0) -> UpgradeDecision:
    now=now or datetime.now(timezone.utc);reasons=[]
    if proposed.draft.solver_tier!="tier2":reasons.append("proposed_candidate_is_not_tier2")
    if incumbent.draft.recovery_id!=proposed.draft.recovery_id:reasons.append("different_recovery")
    if incumbent.draft.input_snapshot_id!=proposed.draft.input_snapshot_id:reasons.append("different_input_snapshot")
    if incumbent.draft.ruleset_version!=proposed.draft.ruleset_version:reasons.append("different_ruleset")
    if incumbent.draft.objective_version!=proposed.draft.objective_version:reasons.append("different_objective")
    if proposed.draft.state_version!=current_state_version:reasons.append("stale_state_version")
    if proposed.draft.expires_at<=now:reasons.append("candidate_expired")
    if not proposed.legal:reasons.append("candidate_not_legal")
    if proposed.draft.metrics.legal_assignments<incumbent.draft.metrics.legal_assignments:
        reasons.append("legal_coverage_regressed")
    if proposed.draft.metrics.unresolved_cases>incumbent.draft.metrics.unresolved_cases:
        reasons.append("unresolved_cases_increased")
    improvement=incumbent.draft.metrics.objective_score-proposed.draft.metrics.objective_score
    if improvement<minimum_objective_improvement:reasons.append("objective_improvement_below_threshold")
    return UpgradeDecision(not reasons,tuple(reasons),improvement)
