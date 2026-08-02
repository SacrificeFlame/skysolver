import pytest

from deployment.recovery_api import RecoveryStore, WorkflowError


def test_carrier_flag_cannot_bypass_joint_feasibility_gate():
    store = RecoveryStore(carrier_writes_enabled=True)
    created = store.create({"disruption_id": "DSP-ORD-0726", "partition_id": "ORD"})
    recovery = created["recovery"]
    approved = store.decide(recovery["id"], {"state_version": 1, "candidate_id": recovery["candidates"][0]["id"], "action": "approve", "operator_id": "test"})
    validated = store.validate(recovery["id"], {"state_version": approved["state_version"], "operator_id": "test"})
    authorized = store.approve(recovery["id"], {"state_version": validated["state_version"], "operator_id": "manager", "operator_role": "duty-manager", "reason": "Verified recovery scope"})
    with pytest.raises(WorkflowError) as blocked:
        store.deploy(recovery["id"], {"state_version": authorized["state_version"], "operator_id": "controller"}, "deploy-key")
    assert blocked.value.code == "joint_feasibility_required"


def test_stale_state_and_unknown_plan_are_rejected():
    store = RecoveryStore()
    recovery = store.create({})["recovery"]
    with pytest.raises(WorkflowError) as stale:
        store.decide(recovery["id"], {"state_version": 0, "candidate_id": recovery["candidates"][0]["id"]})
    assert stale.value.status == 409
    with pytest.raises(WorkflowError) as illegal:
        store.decide(recovery["id"], {"state_version": 1, "candidate_id": "PLAN-C"})
    assert illegal.value.status == 404


def test_override_requires_attributable_reason():
    store = RecoveryStore()
    recovery = store.create({})["recovery"]
    with pytest.raises(WorkflowError) as missing_reason:
        store.decide(recovery["id"], {"state_version": 1, "candidate_id": recovery["candidates"][0]["id"], "action": "override"})
    assert missing_reason.value.code == "reason_required"


def test_synthetic_candidate_declares_missing_joint_feasibility():
    candidate = RecoveryStore().create({})["recovery"]["candidates"][0]
    assert candidate["joint_feasibility"]["deployable"] is False
    assert candidate["joint_feasibility"]["findings"][0]["code"] == "AUTHORITATIVE_RESOURCE_DATA_REQUIRED"


def test_carrier_writes_are_disabled_by_default():
    store = RecoveryStore()
    recovery = store.create({})["recovery"]
    recovery = store.decide(recovery["id"], {"state_version": 1, "candidate_id": recovery["candidates"][0]["id"]})["recovery"]
    recovery = store.validate(recovery["id"], {"state_version": recovery["state_version"]})["recovery"]
    with pytest.raises(WorkflowError) as blocked:
        store.deploy(recovery["id"], {"state_version": recovery["state_version"]}, "k")
    assert blocked.value.status == 403
    assert blocked.value.code == "carrier_writes_disabled"


def test_proposer_cannot_approve_own_plan():
    store = RecoveryStore(carrier_writes_enabled=True)
    recovery = store.create({"operator_id": "scheduler-1"})["recovery"]
    recovery = store.decide(recovery["id"], {"state_version": recovery["state_version"], "candidate_id": recovery["candidates"][0]["id"], "operator_id": "scheduler-1"})["recovery"]
    recovery = store.validate(recovery["id"], {"state_version": recovery["state_version"], "operator_id": "scheduler-1"})["recovery"]
    with pytest.raises(WorkflowError) as rejected:
        store.approve(recovery["id"], {"state_version": recovery["state_version"], "operator_id": "scheduler-1", "operator_role": "duty-manager", "reason": "Self approval"})
    assert rejected.value.code == "segregation_of_duties"


def test_candidates_are_solver_artifacts_with_validation_evidence():
    recovery = RecoveryStore().create({})["recovery"]
    assert {candidate["tier"] for candidate in recovery["candidates"]} == {"tier1", "tier2"}
    assert all(candidate["input_snapshot_id"].startswith("SNP-") for candidate in recovery["candidates"])
    assert all(candidate["assignments"] for candidate in recovery["candidates"])
    assert all(candidate["deployment_readiness"] == "simulation_only" for candidate in recovery["candidates"])
