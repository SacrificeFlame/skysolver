"""Machine-enforced shadow and controlled-production release evidence gate."""

from __future__ import annotations

from dataclasses import asdict,dataclass
import base64
import hashlib
import json
from typing import Protocol


class SignatureVerifier(Protocol):
    def verify(self,payload:bytes,signature:bytes)->bool: ...


@dataclass(frozen=True)
class ReleaseEvidence:
    release_id:str
    image_digest:str
    rules_package_id:str
    rules_certified:bool
    security_assessment_passed:bool
    accessibility_passed:bool
    certified_load_profile_passed:bool
    shadow_accuracy_passed:bool
    reconciliation_passed:bool
    disaster_recovery_exercised:bool
    operational_acceptance_passed:bool
    safety_board_approval_id:str|None
    security_approval_id:str|None
    operator_approval_id:str|None

    def canonical(self)->bytes:
        return json.dumps(asdict(self),sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()


@dataclass(frozen=True)
class GateDecision:
    allowed:bool
    target_environment:str
    blockers:tuple[str,...]
    evidence_sha256:str


def evaluate_release(evidence:ReleaseEvidence,target_environment:str,signature:bytes,verifier:SignatureVerifier)->GateDecision:
    blockers=[]
    if not evidence.image_digest.startswith("sha256:") or len(evidence.image_digest)!=71: blockers.append("image_not_digest_pinned")
    if not verifier.verify(evidence.canonical(),signature): blockers.append("release_evidence_signature_invalid")
    common={"rules_certified":evidence.rules_certified,"security_assessment_not_passed":evidence.security_assessment_passed,
            "accessibility_not_passed":evidence.accessibility_passed,"certified_load_profile_not_passed":evidence.certified_load_profile_passed}
    if not evidence.rules_certified: blockers.append("rules_not_certified")
    if not evidence.security_assessment_passed: blockers.append("security_assessment_not_passed")
    if not evidence.accessibility_passed: blockers.append("accessibility_not_passed")
    if not evidence.certified_load_profile_passed: blockers.append("certified_load_profile_not_passed")
    if target_environment=="controlled-production":
        checks=((evidence.shadow_accuracy_passed,"shadow_accuracy_not_passed"),(evidence.reconciliation_passed,"reconciliation_not_passed"),
                (evidence.disaster_recovery_exercised,"disaster_recovery_not_exercised"),(evidence.operational_acceptance_passed,"operational_acceptance_not_passed"),
                (bool(evidence.safety_board_approval_id),"safety_board_approval_missing"),(bool(evidence.security_approval_id),"security_approval_missing"),
                (bool(evidence.operator_approval_id),"operator_approval_missing"))
        blockers.extend(code for passed,code in checks if not passed)
    elif target_environment!="shadow-production": blockers.append("target_environment_not_releasable")
    return GateDecision(not blockers,target_environment,tuple(blockers),hashlib.sha256(evidence.canonical()).hexdigest())


class KmsSignatureVerifier:
    def __init__(self,key_id:str,kms_client): self.key_id=key_id;self.kms=kms_client
    def verify(self,payload:bytes,signature:bytes)->bool:
        response=self.kms.verify(KeyId=self.key_id,Message=payload,MessageType="RAW",Signature=signature,SigningAlgorithm="ECDSA_SHA_256")
        return bool(response.get("SignatureValid"))
