"""Production recovery transition service backed by the durable repository.

The service authorizes state transitions only. Solvers, the independent rules
service, feasibility evaluators and carrier adapters remain separate systems.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable
import uuid

from core.candidate_lifecycle import ImmutableCandidate
from state.durable_recovery_store import DurableRecoveryRepository, MutationReceipt, WorkflowMutation


class RecoveryTransitionRejected(RuntimeError):
    def __init__(self,code:str,message:str):super().__init__(message);self.code=code


@dataclass(frozen=True)
class CommandContext:
    tenant_id:str
    actor_subject:str
    actor_role:str
    idempotency_key:str
    correlation_id:str
    causation_id:str|None
    expected_version:int


class DurableRecoveryWorkflow:
    def __init__(self,repository:DurableRecoveryRepository,
                 certificate_verifier:Callable[[dict[str,Any],ImmutableCandidate],bool],
                 hold_verifier:Callable[[str,ImmutableCandidate],bool]):
        self.repository=repository;self.certificate_verifier=certificate_verifier;self.hold_verifier=hold_verifier

    @staticmethod
    def _now(now=None):return now or datetime.now(timezone.utc)
    @staticmethod
    def _candidate_summary(candidate:ImmutableCandidate)->dict[str,Any]:
        draft=candidate.draft
        return {"candidate_id":candidate.candidate_id,"candidate_version":candidate.candidate_version,
            "content_sha256":candidate.content_sha256,"input_snapshot_id":draft.input_snapshot_id,
            "solver_tier":draft.solver_tier,"solver_version":draft.solver_version,
            "ruleset_version":draft.ruleset_version,"objective_version":draft.objective_version,
            "state_version":draft.state_version,"expires_at":draft.expires_at.isoformat(),
            "artifact_version_id":candidate.artifact.version_id,"legal":candidate.legal,
            "metrics":asdict(draft.metrics)}

    def _load(self,ctx:CommandContext,recovery_id:str)->dict[str,Any]:
        stored=self.repository.get_snapshot(ctx.tenant_id,recovery_id)
        if stored is None:raise RecoveryTransitionRejected("recovery_not_found","Recovery does not exist")
        if stored["state_version"]!=ctx.expected_version:
            raise RecoveryTransitionRejected("stale_state",f"Expected recovery version {stored['state_version']}")
        return dict(stored["snapshot"])

    def _persist(self,ctx:CommandContext,recovery_id:str,partition_id:str,command_type:str,
                 event_type:str,snapshot:dict[str,Any],status:str)->MutationReceipt:
        new_version=ctx.expected_version+1;snapshot={**snapshot,"state_version":new_version,
            "updated_at":datetime.now(timezone.utc).isoformat()}
        return self.repository.mutate(WorkflowMutation(tenant_id=ctx.tenant_id,recovery_id=recovery_id,
            expected_version=ctx.expected_version,idempotency_key=ctx.idempotency_key,
            command_type=command_type,event_type=event_type,actor_subject=ctx.actor_subject,
            correlation_id=ctx.correlation_id,causation_id=ctx.causation_id,partition_id=partition_id,
            request={"actor_role":ctx.actor_role},snapshot=snapshot,
            response={"action_status":status,"recovery":snapshot}))

    def create(self,ctx:CommandContext,*,disruption_id:str,partition_id:str,objective_version:str,
               now=None)->MutationReceipt:
        if ctx.expected_version!=0:raise RecoveryTransitionRejected("invalid_initial_version","New recovery expects version zero")
        recovery_id=f"REC-{uuid.uuid4().hex[:16].upper()}";created=self._now(now)
        snapshot={"id":recovery_id,"tenant_id":ctx.tenant_id,"disruption_id":disruption_id,
            "partition_id":partition_id,"objective_version":objective_version,"status":"solving",
            "proposed_by":ctx.actor_subject,"selected_candidate":None,"validation":None,
            "joint_feasibility":None,"hold_id":None,"approval":None,"deployment_authorized":False,
            "created_at":created.isoformat()}
        return self._persist(ctx,recovery_id,partition_id,"create_recovery","RecoveryCreated",snapshot,"accepted")

    def select_candidate(self,ctx:CommandContext,recovery_id:str,candidate:ImmutableCandidate,
                         now=None)->MutationReceipt:
        state=self._load(ctx,recovery_id);current=self._now(now)
        if candidate.draft.tenant_id!=ctx.tenant_id or candidate.draft.recovery_id!=recovery_id:
            raise RecoveryTransitionRejected("foreign_candidate","Candidate belongs to another tenant or recovery")
        if candidate.draft.state_version!=ctx.expected_version:
            raise RecoveryTransitionRejected("stale_candidate","Candidate was solved from another state version")
        if candidate.draft.expires_at<=current:raise RecoveryTransitionRejected("candidate_expired","Candidate has expired")
        if not candidate.legal:raise RecoveryTransitionRejected("illegal_candidate","Illegal candidate cannot be selected")
        if state["status"] not in {"solving","awaiting_review"}:
            raise RecoveryTransitionRejected("invalid_transition","Recovery is not accepting candidate selection")
        state.update(status="awaiting_validation",selected_candidate=self._candidate_summary(candidate),
                     validation=None,joint_feasibility=None,hold_id=None,approval=None,deployment_authorized=False)
        return self._persist(ctx,recovery_id,state["partition_id"],"select_candidate","CandidateSelected",state,"selected")

    def record_validation(self,ctx:CommandContext,recovery_id:str,candidate:ImmutableCandidate,
                          validation:dict[str,Any],now=None)->MutationReceipt:
        state=self._load(ctx,recovery_id);self._assert_selected(state,candidate,self._now(now))
        if state["status"]!="awaiting_validation":
            raise RecoveryTransitionRejected("invalid_transition","Recovery is not awaiting validation")
        certificate=validation.get("certificate")
        if not validation.get("valid") or validation.get("findings") or not certificate:
            raise RecoveryTransitionRejected("independent_validation_failed","Independent validation did not produce a clean certificate")
        if certificate.get("tenant_id")!=ctx.tenant_id or certificate.get("recovery_id")!=recovery_id \
                or certificate.get("candidate_id")!=candidate.candidate_id:
            raise RecoveryTransitionRejected("certificate_binding_invalid","Certificate identity does not match candidate")
        if certificate.get("state_version")!=ctx.expected_version or certificate.get("ruleset_version")!=candidate.draft.ruleset_version:
            raise RecoveryTransitionRejected("certificate_binding_invalid","Certificate version or ruleset does not match")
        if certificate.get("assurance_level")!="operator_approved_certified":
            raise RecoveryTransitionRejected("certificate_assurance_insufficient","Certificate is not operator-approved")
        if not self.certificate_verifier(certificate,candidate):
            raise RecoveryTransitionRejected("certificate_signature_invalid","Certificate signature or artifact binding is invalid")
        state.update(status="awaiting_joint_feasibility",validation={"certificate":certificate,
            "rules_execution":validation.get("rules_execution"),"validated_at":certificate.get("validated_at")})
        return self._persist(ctx,recovery_id,state["partition_id"],"record_validation","CandidateValidated",state,"validated")

    def record_joint_feasibility(self,ctx:CommandContext,recovery_id:str,candidate:ImmutableCandidate,
                                 feasibility:dict[str,Any],hold_id:str,now=None)->MutationReceipt:
        state=self._load(ctx,recovery_id);self._assert_selected(state,candidate,self._now(now))
        if state["status"]!="awaiting_joint_feasibility":
            raise RecoveryTransitionRejected("invalid_transition","Recovery is not awaiting joint feasibility")
        if not feasibility.get("deployable") or feasibility.get("findings"):
            raise RecoveryTransitionRejected("joint_feasibility_failed","Crew, aircraft, airport and passenger feasibility did not pass")
        if not self.hold_verifier(hold_id,candidate):
            raise RecoveryTransitionRejected("resource_hold_invalid","Candidate resource hold is missing, stale or expired")
        state.update(status="awaiting_approval",joint_feasibility=feasibility,hold_id=hold_id)
        return self._persist(ctx,recovery_id,state["partition_id"],"record_feasibility","JointFeasibilityPassed",state,"feasible")

    def approve(self,ctx:CommandContext,recovery_id:str,candidate:ImmutableCandidate,reason:str,
                now=None)->MutationReceipt:
        state=self._load(ctx,recovery_id);self._assert_selected(state,candidate,self._now(now))
        if state["status"]!="awaiting_approval":raise RecoveryTransitionRejected("invalid_transition","Recovery is not awaiting approval")
        if ctx.actor_role!="duty-manager":raise RecoveryTransitionRejected("approval_role_required","Duty-manager role is required")
        if ctx.actor_subject==state["proposed_by"]:raise RecoveryTransitionRejected("segregation_of_duties","Proposer cannot approve")
        if len(reason.strip())<3:raise RecoveryTransitionRejected("reason_required","Approval reason is required")
        state.update(status="approved",approval={"actor_subject":ctx.actor_subject,"actor_role":ctx.actor_role,
            "reason":reason.strip(),"approved_at":self._now(now).isoformat(),"candidate_id":candidate.candidate_id,
            "candidate_version":candidate.candidate_version})
        return self._persist(ctx,recovery_id,state["partition_id"],"approve_recovery","RecoveryApproved",state,"approved")

    def authorize_deployment(self,ctx:CommandContext,recovery_id:str,candidate:ImmutableCandidate,
                             now=None)->MutationReceipt:
        state=self._load(ctx,recovery_id);self._assert_selected(state,candidate,self._now(now))
        if state["status"]!="approved" or not state.get("validation") or not state.get("joint_feasibility"):
            raise RecoveryTransitionRejected("deployment_prerequisites_missing","Validation, feasibility and approval are required")
        if ctx.actor_role!="deployment-controller":
            raise RecoveryTransitionRejected("deployment_role_required","Deployment-controller role is required")
        actors={state["proposed_by"],state["approval"]["actor_subject"]}
        if ctx.actor_subject in actors:raise RecoveryTransitionRejected("segregation_of_duties","Controller must be distinct")
        if not self.hold_verifier(state["hold_id"],candidate):
            raise RecoveryTransitionRejected("resource_hold_invalid","Resource hold expired before deployment")
        state.update(status="deployment_authorized",deployment_authorized=True,
            deployment_authorized_by=ctx.actor_subject,deployment_authorized_at=self._now(now).isoformat())
        return self._persist(ctx,recovery_id,state["partition_id"],"authorize_deployment","DeploymentAuthorized",state,"authorized")

    @staticmethod
    def _assert_selected(state:dict[str,Any],candidate:ImmutableCandidate,now:datetime)->None:
        selected=state.get("selected_candidate") or {}
        if selected.get("candidate_id")!=candidate.candidate_id or selected.get("content_sha256")!=candidate.content_sha256:
            raise RecoveryTransitionRejected("candidate_version_mismatch","Selected candidate artifact does not match")
        if candidate.draft.expires_at<=now:raise RecoveryTransitionRejected("candidate_expired","Candidate expired during review")
