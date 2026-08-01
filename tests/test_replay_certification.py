from chaos.replay import CertificationEvidence, evaluate_certification_evidence


def test_toy_run_cannot_be_reported_as_certified():
    result = evaluate_certification_evidence(CertificationEvidence(
        affected_flight_records=2400,
        solvable_cases=100,
        legal_tier1_cases=100,
        tier1_elapsed_seconds=0.5,
    ))
    assert result.status == "NOT_CERTIFIED"
    assert "minimum_flight_volume_not_met" in result.blockers
    assert "passenger_recovery_not_computed" in result.blockers


def test_certification_requires_every_resilience_dimension():
    evidence = CertificationEvidence(
        affected_flight_records=50100,
        solvable_cases=100,
        legal_tier1_cases=100,
        tier1_elapsed_seconds=299,
        passenger_recovery_computed=True,
        tier3_generated=True,
        contention_exercised=True,
        worker_loss_exercised=True,
        regional_failover_exercised=True,
        illegal_assignments_accepted=0,
    )
    result = evaluate_certification_evidence(evidence)
    assert result.status == "CERTIFICATION_EVIDENCE_ACCEPTED"
    assert result.blockers == ()


def test_illegal_assignment_always_fails_gate():
    evidence = CertificationEvidence(
        affected_flight_records=50100,
        solvable_cases=1,
        legal_tier1_cases=1,
        tier1_elapsed_seconds=1,
        passenger_recovery_computed=True,
        tier3_generated=True,
        contention_exercised=True,
        worker_loss_exercised=True,
        regional_failover_exercised=True,
        illegal_assignments_accepted=1,
    )
    assert "illegal_assignment_accepted" in evaluate_certification_evidence(evidence).blockers
