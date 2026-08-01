from dataclasses import replace
from datetime import datetime,timedelta,timezone

import pytest

from core.candidate_lifecycle import CandidateDraft,CandidateMetrics,ImmutableCandidate
from core.durable_recovery_workflow import CommandContext,DurableRecoveryWorkflow,RecoveryTransitionRejected
from state.durable_recovery_store import MutationReceipt
from state.immutable_artifacts import ArtifactReference


NOW=datetime(2026,8,2,tzinfo=timezone.utc)
class Repository:
    def __init__(self):self.snapshots={}
    def get_snapshot(self,tenant,recovery):
        value=self.snapshots.get((tenant,recovery));return None if value is None else {"state_version":value["state_version"],"snapshot":value}
    def mutate(self,mutation):
        self.snapshots[(mutation.tenant_id,mutation.recovery_id)]=mutation.snapshot
        return MutationReceipt("event",mutation.expected_version+1,{**mutation.response,"state_version":mutation.expected_version+1},False)


def context(version,actor="scheduler-1",role="scheduler",key="command-key-1"):
    return CommandContext("airline-1",actor,role,key,"correlation-1",None,version)


def candidate(recovery_id,state=1,expires=None):
    draft=CandidateDraft("airline-1",recovery_id,"SNP-1","tier1","solver-1","RULE-1","OBJ-1",state,
        ({"crew_id":"IC-1"},),(),(),(),CandidateMetrics(1,0,1,0,0,0,0,1),
        {"valid":True,"findings":[]},expires or NOW+timedelta(minutes=20))
    artifact=ArtifactReference("bucket","key","v1","a"*64,"kms",(NOW+timedelta(days=1)).isoformat(),"candidate")
    return ImmutableCandidate("CAN-1",1,"a"*64,artifact,draft,NOW)


def setup_selected():
    repository=Repository();workflow=DurableRecoveryWorkflow(repository,lambda cert,can:cert.get("signature")=="valid",lambda hold,can:hold=="HLD-1")
    created=workflow.create(context(0),disruption_id="DSP-1",partition_id="DEL",objective_version="OBJ-1",now=NOW)
    recovery_id=created.response["recovery"]["id"]
    selected=workflow.select_candidate(context(1,key="select-key"),recovery_id,candidate(recovery_id),now=NOW)
    return repository,workflow,recovery_id,candidate(recovery_id),selected


def certificate(recovery_id,state=2,assurance="operator_approved_certified"):
    return {"certificate_id":"CERT-1","tenant_id":"airline-1","recovery_id":recovery_id,
        "candidate_id":"CAN-1","state_version":state,"ruleset_version":"RULE-1",
        "assurance_level":assurance,"signature":"valid","validated_at":NOW.isoformat()}


def test_complete_transition_chain_requires_three_distinct_roles():
    _,workflow,recovery_id,can,_=setup_selected()
    workflow.record_validation(context(2,actor="validator",role="validation-service",key="validate-key"),
        recovery_id,can,{"valid":True,"findings":[],"certificate":certificate(recovery_id)},now=NOW)
    workflow.record_joint_feasibility(context(3,actor="feasibility",role="service",key="feasible-key"),
        recovery_id,can,{"deployable":True,"findings":[]},"HLD-1",now=NOW)
    workflow.approve(context(4,actor="manager-1",role="duty-manager",key="approve-key"),recovery_id,can,"Reviewed evidence",now=NOW)
    result=workflow.authorize_deployment(context(5,actor="controller-1",role="deployment-controller",key="deploy-key"),recovery_id,can,now=NOW)
    assert result.response["recovery"]["deployment_authorized"] is True
    assert result.response["state_version"]==6


def test_demo_or_unverified_certificate_cannot_advance():
    _,workflow,recovery_id,can,_=setup_selected()
    with pytest.raises(RecoveryTransitionRejected,match="operator-approved"):
        workflow.record_validation(context(2,key="validation-key"),recovery_id,can,
            {"valid":True,"findings":[],"certificate":certificate(recovery_id,assurance="demo")},now=NOW)


def test_failed_joint_feasibility_cannot_advance():
    _,workflow,recovery_id,can,_=setup_selected()
    workflow.record_validation(context(2,key="validation-key"),recovery_id,can,
        {"valid":True,"findings":[],"certificate":certificate(recovery_id)},now=NOW)
    with pytest.raises(RecoveryTransitionRejected,match="did not pass"):
        workflow.record_joint_feasibility(context(3,key="feasibility-key"),recovery_id,can,
            {"deployable":False,"findings":[{"code":"GATE_CONFLICT"}]},"HLD-1",now=NOW)


def test_expired_candidate_is_rejected_at_every_review_boundary():
    repository=Repository();workflow=DurableRecoveryWorkflow(repository,lambda *_:True,lambda *_:True)
    created=workflow.create(context(0),disruption_id="DSP",partition_id="DEL",objective_version="OBJ",now=NOW)
    recovery=created.response["recovery"]["id"]
    with pytest.raises(RecoveryTransitionRejected,match="expired"):
        workflow.select_candidate(context(1,key="expired-key"),recovery,candidate(recovery,expires=NOW),now=NOW)


def test_proposer_cannot_approve_and_approver_cannot_deploy():
    _,workflow,recovery_id,can,_=setup_selected()
    workflow.record_validation(context(2,key="v-key-123"),recovery_id,can,
        {"valid":True,"findings":[],"certificate":certificate(recovery_id)},now=NOW)
    workflow.record_joint_feasibility(context(3,key="f-key-123"),recovery_id,can,
        {"deployable":True,"findings":[]},"HLD-1",now=NOW)
    with pytest.raises(RecoveryTransitionRejected,match="Proposer"):
        workflow.approve(context(4,actor="scheduler-1",role="duty-manager",key="a-key-123"),recovery_id,can,"reason",now=NOW)
    workflow.approve(context(4,actor="manager-1",role="duty-manager",key="a-key-456"),recovery_id,can,"reason",now=NOW)
    with pytest.raises(RecoveryTransitionRejected,match="distinct"):
        workflow.authorize_deployment(context(5,actor="manager-1",role="deployment-controller",key="d-key-123"),recovery_id,can,now=NOW)
