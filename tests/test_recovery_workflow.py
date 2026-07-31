import pytest

from deployment.recovery_api import RecoveryStore, WorkflowError


def test_complete_recovery_workflow_and_idempotent_deploy():
    store = RecoveryStore()
    created = store.create({"disruption_id": "DSP-ORD-0726", "partition_id": "ORD"})
    recovery = created["recovery"]
    approved = store.decide(recovery["id"], {"state_version": 1, "candidate_id": "PLAN-A", "action": "approve", "operator_id": "test"})
    validated = store.validate(recovery["id"], {"state_version": approved["state_version"], "operator_id": "test"})
    deployed = store.deploy(recovery["id"], {"state_version": validated["state_version"], "operator_id": "test"}, "deploy-key")
    repeated = store.deploy(recovery["id"], {"state_version": validated["state_version"]}, "deploy-key")
    assert deployed == repeated
    assert deployed["action_status"] == "deployed"
    assert all(x["status"] == "acknowledged" for x in deployed["acknowledgements"])


def test_stale_state_and_illegal_plan_are_rejected():
    store = RecoveryStore()
    recovery = store.create({})["recovery"]
    with pytest.raises(WorkflowError) as stale:
        store.decide(recovery["id"], {"state_version": 0, "candidate_id": "PLAN-A"})
    assert stale.value.status == 409
    with pytest.raises(WorkflowError) as illegal:
        store.decide(recovery["id"], {"state_version": 1, "candidate_id": "PLAN-C"})
    assert illegal.value.status == 422


def test_override_requires_attributable_reason():
    store = RecoveryStore()
    recovery = store.create({})["recovery"]
    with pytest.raises(WorkflowError) as missing_reason:
        store.decide(recovery["id"], {"state_version": 1, "candidate_id": "PLAN-A", "action": "override"})
    assert missing_reason.value.code == "reason_required"


def test_deployment_can_be_rolled_back_with_new_version():
    store = RecoveryStore()
    recovery = store.create({})["recovery"]
    recovery = store.decide(recovery["id"], {"state_version": 1, "candidate_id": "PLAN-A"})["recovery"]
    recovery = store.validate(recovery["id"], {"state_version": recovery["state_version"]})["recovery"]
    recovery = store.deploy(recovery["id"], {"state_version": recovery["state_version"]}, "k")["recovery"]
    result = store.rollback(recovery["id"], {"state_version": recovery["state_version"], "reason": "test"})
    assert result["action_status"] == "rolled_back"
    assert result["recovery"]["deployed"] is False
