from datetime import datetime, timedelta, timezone

import pytest

from rules.governance import GovernanceError, RulePackageRegistry, RulePackageStatus


KEY = b"test-only-signing-key"
CONTENT = {"jurisdiction": "DGCA", "rules": [{"id": "FDP-1", "expression": "demo"}]}


def submitted(registry, version="v1"):
    current = datetime.now(timezone.utc)
    return registry.submit(tenant_id="airline", version=version, effective_from=current - timedelta(minutes=1),
                           effective_until=current + timedelta(days=365), submitted_by="author",
                           content=CONTENT, signature=registry.sign(CONTENT, KEY), signing_key_id="key-1")


def approved(registry, version="v1"):
    package = submitted(registry, version)
    registry.approve(package.package_id, "ops-approver", "airline-operations", "Operational review complete")
    return registry.approve(package.package_id, "compliance-approver", "regulatory-compliance", "Regulatory review complete")


def shadow_pass(registry, version="v1"):
    package = approved(registry, version); registry.begin_shadow(package.package_id)
    return registry.record_shadow(package.package_id, cases_evaluated=1000, expected_matches=1000,
                                  unexpected_differences=0, blocking_findings=0, artifact_sha256="a" * 64)


def test_invalid_signature_is_rejected():
    registry = RulePackageRegistry({"key-1": KEY})
    with pytest.raises(GovernanceError) as invalid:
        registry.submit(tenant_id="airline", version="v1", effective_from=datetime.now(timezone.utc),
                        effective_until=None, submitted_by="author", content=CONTENT, signature="bad", signing_key_id="key-1")
    assert invalid.value.code == "invalid_signature"


def test_four_eyes_and_distinct_authorities_are_required():
    registry = RulePackageRegistry({"key-1": KEY}); package = submitted(registry)
    with pytest.raises(GovernanceError) as self_approval:
        registry.approve(package.package_id, "author", "airline-operations", "Self review")
    assert self_approval.value.code == "four_eyes_required"
    registry.approve(package.package_id, "ops", "airline-operations", "Operations approved")
    assert package.status is RulePackageStatus.DRAFT
    registry.approve(package.package_id, "compliance", "regulatory-compliance", "Compliance approved")
    assert package.status is RulePackageStatus.APPROVED


def test_shadow_differences_block_activation():
    registry = RulePackageRegistry({"key-1": KEY}); package = approved(registry); registry.begin_shadow(package.package_id)
    registry.record_shadow(package.package_id, cases_evaluated=100, expected_matches=99, unexpected_differences=1,
                           blocking_findings=0, artifact_sha256="b" * 64)
    with pytest.raises(GovernanceError) as blocked:
        registry.activate(package.package_id)
    assert blocked.value.code == "shadow_gate_failed"


def test_passing_shadow_package_activates_and_prior_package_can_rollback():
    registry = RulePackageRegistry({"key-1": KEY})
    first = shadow_pass(registry, "v1"); registry.activate(first.package_id)
    second = shadow_pass(registry, "v2"); registry.activate(second.package_id)
    assert first.status is RulePackageStatus.RETIRED
    assert registry.active("airline").version == "v2"
    registry.rollback("airline", first.package_id)
    assert registry.active("airline").version == "v1"
