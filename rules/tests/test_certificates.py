import pytest

from rules.certificates import CertificateError, CertificateIssuer


def issuer():
    return CertificateIssuer("kms-demo-key", b"test-key", "validation-service-b", "1.0.0", "demo_in_process_not_certified")


def test_certificate_is_bound_to_snapshot_candidate_and_rules():
    service = issuer(); snapshot = {"version": 4}; candidate = {"crew": "C1"}; rules = {"version": "R1"}
    certificate = service.issue(tenant_id="airline", recovery_id="R1", candidate_id="C1", input_snapshot=snapshot,
                                candidate=candidate, rules_package=rules, ruleset_version="R1", state_version=4, findings=[])
    assert service.verify(certificate, input_snapshot=snapshot, candidate=candidate, rules_package=rules)
    assert certificate.assurance_level == "demo_in_process_not_certified"


def test_tampered_candidate_invalidates_certificate():
    service = issuer(); snapshot = {"version": 4}; candidate = {"crew": "C1"}; rules = {"version": "R1"}
    certificate = service.issue(tenant_id="airline", recovery_id="R1", candidate_id="C1", input_snapshot=snapshot,
                                candidate=candidate, rules_package=rules, ruleset_version="R1", state_version=4, findings=[])
    assert not service.verify(certificate, input_snapshot=snapshot, candidate={"crew": "C2"}, rules_package=rules)


def test_findings_prevent_certificate_issuance():
    with pytest.raises(CertificateError) as rejected:
        issuer().issue(tenant_id="airline", recovery_id="R1", candidate_id="C1", input_snapshot={}, candidate={},
                       rules_package={}, ruleset_version="R1", state_version=1, findings=[{"code": "FDP"}])
    assert rejected.value.code == "legality_findings"
