from deployment.release_gate import ReleaseEvidence,evaluate_release


class Verifier:
    def __init__(self,valid=True):self.valid=valid
    def verify(self,payload,signature):return self.valid and signature==b"signed"


def evidence(**changes):
    values=dict(release_id="REL-1",image_digest="sha256:"+"a"*64,rules_package_id="RPK-1",rules_certified=True,
                security_assessment_passed=True,accessibility_passed=True,certified_load_profile_passed=True,
                shadow_accuracy_passed=True,reconciliation_passed=True,disaster_recovery_exercised=True,
                operational_acceptance_passed=True,safety_board_approval_id="SAFE-1",security_approval_id="SEC-1",operator_approval_id="OPS-1")
    values.update(changes);return ReleaseEvidence(**values)


def test_controlled_production_requires_complete_signed_evidence():
    assert evaluate_release(evidence(),"controlled-production",b"signed",Verifier()).allowed


def test_missing_any_safety_gate_blocks_release():
    decision=evaluate_release(evidence(rules_certified=False,shadow_accuracy_passed=False,safety_board_approval_id=None),"controlled-production",b"signed",Verifier())
    assert not decision.allowed
    assert {"rules_not_certified","shadow_accuracy_not_passed","safety_board_approval_missing"}<=set(decision.blockers)


def test_invalid_signature_and_floating_image_block_shadow():
    decision=evaluate_release(evidence(image_digest="latest"),"shadow-production",b"bad",Verifier(False))
    assert set(decision.blockers)=={"image_not_digest_pinned","release_evidence_signature_invalid"}
