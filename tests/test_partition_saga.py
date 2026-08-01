import pytest

from state.reconciliation import PartitionMoveRegistry, SagaError, SagaStatus


def create(registry):
    return registry.create(tenant_id="airline", recovery_id="R1", resource_type="crew", resource_id="IC-184",
                           source_partition="DEL", destination_partition="BOM", movement_reference="AI421",
                           correlation_id="correlation-1", idempotency_key="move-1")


def ready_to_commit(registry):
    saga = create(registry)
    saga = registry.reserve_source(saga.saga_id, saga.state_version, "src-res")
    saga = registry.reserve_destination(saga.saga_id, saga.state_version, "dst-res")
    saga = registry.validate(saga.saga_id, saga.state_version, "LGC-1", "MOV-1", [])
    return registry.begin_commit(saga.saga_id, saga.state_version)


def test_both_partitions_must_ack_before_completion():
    registry = PartitionMoveRegistry(); saga = ready_to_commit(registry)
    saga = registry.acknowledge_partition(saga.saga_id, saga.state_version, "DEL", True)
    assert saga.status is SagaStatus.PARTIAL
    saga = registry.acknowledge_partition(saga.saga_id, saga.state_version, "BOM", True)
    assert saga.status is SagaStatus.COMPLETE


def test_destination_nack_triggers_compensation():
    registry = PartitionMoveRegistry(); saga = ready_to_commit(registry)
    saga = registry.acknowledge_partition(saga.saga_id, saga.state_version, "DEL", True)
    saga = registry.acknowledge_partition(saga.saga_id, saga.state_version, "BOM", False)
    assert saga.status is SagaStatus.COMPENSATING
    saga = registry.complete_compensation(saga.saga_id, saga.state_version, True, True)
    assert saga.status is SagaStatus.COMPENSATED


def test_legality_finding_prevents_commit_and_releases_reservations():
    registry = PartitionMoveRegistry(); saga = create(registry)
    saga = registry.reserve_source(saga.saga_id, saga.state_version, "src")
    saga = registry.reserve_destination(saga.saga_id, saga.state_version, "dst")
    saga = registry.validate(saga.saga_id, saga.state_version, "", "", [{"code": "DUTY_LIMIT"}])
    assert saga.status is SagaStatus.COMPENSATING
    with pytest.raises(SagaError): registry.begin_commit(saga.saga_id, saga.state_version)


def test_stale_writer_and_unknown_partition_are_rejected():
    registry = PartitionMoveRegistry(); saga = ready_to_commit(registry)
    with pytest.raises(SagaError) as stale: registry.acknowledge_partition(saga.saga_id, 1, "DEL", True)
    assert stale.value.code == "stale_state"
    with pytest.raises(SagaError) as unknown: registry.acknowledge_partition(saga.saga_id, saga.state_version, "HYD", True)
    assert unknown.value.code == "unknown_partition"


def test_creation_is_idempotent():
    registry = PartitionMoveRegistry()
    assert create(registry).saga_id == create(registry).saga_id
