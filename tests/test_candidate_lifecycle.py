from dataclasses import replace
from datetime import datetime,timedelta,timezone
import hashlib,json

from core.candidate_lifecycle import CandidateDraft,CandidateLifecycle,CandidateMetrics,evaluate_upgrade
from state.immutable_artifacts import ArtifactReference


NOW=datetime(2026,8,2,tzinfo=timezone.utc)
class Writer:
    def put(self,**values):
        body=json.dumps(values["value"],sort_keys=True,separators=(",",":"),default=str).encode();digest=hashlib.sha256(body).hexdigest()
        return ArtifactReference("bucket","key","v1",digest,"kms",(NOW+timedelta(days=1)).isoformat(),"candidate")
class Repository:
    def __init__(self):self.items=[]
    def insert(self,candidate):self.items.append(candidate)


def draft(tier="tier1",score=100,legal=2,unresolved=1,state=4,snapshot="SNP-1",rules="RULE-1"):
    assignments=tuple({"crew_id":f"IC-{i}","flight_id":f"AI-{i}"} for i in range(legal))
    return CandidateDraft("airline-1","REC-1",snapshot,tier,"solver-1",rules,"OBJ-1",state,
        assignments,(),(),tuple({"id":i} for i in range(unresolved)),
        CandidateMetrics(legal,unresolved,legal,20,2,1000,0.2,score),
        {"valid":True,"findings":[],"certificate_id":"CERT-1"},NOW+timedelta(minutes=20))


def create(value):return CandidateLifecycle(Writer(),Repository()).create(value,NOW)


def test_candidate_is_unique_immutable_and_indexed_after_artifact_write():
    repository=Repository();candidate=CandidateLifecycle(Writer(),repository).create(draft(),NOW)
    assert candidate.candidate_id.startswith("CAN-") and candidate.candidate_version==1
    assert len(repository.items)==1 and repository.items[0] is candidate


def test_tier2_upgrade_accepts_same_snapshot_legal_non_regressing_improvement():
    incumbent=create(draft());proposed=create(draft(tier="tier2",score=80,legal=3,unresolved=0))
    decision=evaluate_upgrade(incumbent,proposed,current_state_version=4,now=NOW,minimum_objective_improvement=5)
    assert decision.accepted and decision.objective_improvement==20


def test_tier2_upgrade_rejects_stale_foreign_or_regressing_candidate():
    incumbent=create(draft(legal=3,unresolved=1));proposed=create(draft(tier="tier2",score=120,legal=2,
        unresolved=2,state=3,snapshot="SNP-2",rules="RULE-2"))
    decision=evaluate_upgrade(incumbent,proposed,current_state_version=4,now=NOW,minimum_objective_improvement=1)
    assert not decision.accepted
    assert {"different_input_snapshot","different_ruleset","stale_state_version","legal_coverage_regressed",
            "unresolved_cases_increased","objective_improvement_below_threshold"}<=set(decision.reasons)


def test_illegal_tier2_never_replaces_legal_incumbent():
    incumbent=create(draft());proposed=create(replace(draft(tier="tier2",score=1),legality_certificate=None))
    assert "candidate_not_legal" in evaluate_upgrade(incumbent,proposed,current_state_version=4,now=NOW).reasons
