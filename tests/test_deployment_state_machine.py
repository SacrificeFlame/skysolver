import pytest

from deployment.command_state import CommandStatus, DeploymentConflict, DeploymentRegistry, DeploymentStatus


def resources(irreversible=False):
    return [
        {"resource_type": "crew", "resource_id": "IC-184", "target_system": "crew-ops", "action": "reassign", "reversible": True},
        {"resource_type": "passenger", "resource_id": "PNR-42", "target_system": "dcs", "action": "ticket", "reversible": not irreversible},
    ]


def create(registry, key="idem-12345678", irreversible=False):
    return registry.create(tenant_id="airline", recovery_id="RCV-1", candidate_id="CAN-1", candidate_version=4,
                           idempotency_key=key, correlation_id="correlation-1", requested_by="controller", resources=resources(irreversible))


def send_and_ack(registry, deployment, index, accepted=True):
    command = deployment.commands[index]
    deployment = registry.mark_sent(deployment.deployment_id, command.command_id, deployment.state_version, f"send-{index}")
    return registry.acknowledge(deployment.deployment_id, command.command_id, deployment.state_version, accepted=accepted,
                                adapter_reference=f"ack-{index}", failure_code=None if accepted else "CONFLICT")


def test_complete_requires_every_required_ack():
    registry = DeploymentRegistry(); deployment = create(registry)
    deployment = send_and_ack(registry, deployment, 0)
    assert deployment.status is DeploymentStatus.PUBLISHING
    deployment = send_and_ack(registry, deployment, 1)
    assert deployment.status is DeploymentStatus.COMPLETE
    assert deployment.to_dict()["complete"] is True


def test_nack_after_ack_is_partial_and_retryable():
    registry = DeploymentRegistry(); deployment = create(registry)
    deployment = send_and_ack(registry, deployment, 0)
    deployment = send_and_ack(registry, deployment, 1, accepted=False)
    assert deployment.status is DeploymentStatus.PARTIAL
    failed = deployment.commands[1]
    deployment = registry.retry(deployment.deployment_id, failed.command_id, deployment.state_version)
    assert failed.status is CommandStatus.QUEUED
    assert deployment.status is DeploymentStatus.QUEUED


def test_stale_ack_is_rejected():
    registry = DeploymentRegistry(); deployment = create(registry)
    command = deployment.commands[0]
    deployment = registry.mark_sent(deployment.deployment_id, command.command_id, deployment.state_version, "send")
    with pytest.raises(DeploymentConflict, match="Expected deployment version") as stale:
        registry.acknowledge(deployment.deployment_id, command.command_id, 1, accepted=True, adapter_reference="ack")
    assert stale.value.code == "stale_state"


def test_idempotent_create_returns_same_deployment():
    registry = DeploymentRegistry()
    assert create(registry).deployment_id == create(registry).deployment_id


def test_irreversible_ack_requires_new_recovery_not_fake_rollback():
    registry = DeploymentRegistry(); deployment = create(registry, irreversible=True)
    deployment = send_and_ack(registry, deployment, 0)
    deployment = send_and_ack(registry, deployment, 1)
    deployment = registry.compensate(deployment.deployment_id, deployment.state_version)
    assert deployment.status is DeploymentStatus.REQUIRES_NEW_RECOVERY
    assert deployment.commands[0].status is CommandStatus.COMPENSATION_QUEUED
    assert deployment.commands[1].status is CommandStatus.IRREVERSIBLE


def test_reversible_actions_can_be_compensated_with_ack():
    registry = DeploymentRegistry(); deployment = create(registry)
    deployment = send_and_ack(registry, deployment, 0)
    deployment = send_and_ack(registry, deployment, 1)
    deployment = registry.compensate(deployment.deployment_id, deployment.state_version)
    for command in deployment.commands:
        deployment = registry.acknowledge_compensation(deployment.deployment_id, command.command_id, deployment.state_version, f"comp-{command.command_id}")
    assert deployment.status is DeploymentStatus.COMPENSATED
