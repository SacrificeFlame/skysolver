from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from integrations.adapters.base import (
    AdapterCapabilities, AdapterPage, AdapterSecurityError, ApprovalEvidence,
    CarrierAdapter, CircuitBreaker, DeploymentCommand, PublishResult, PublishStatus,
    SourceTimeout, UnsupportedContract, redact_for_telemetry,
)


class Verifier:
    def __init__(self, valid=True): self.valid=valid
    def verify(self, _key_id, _content, _signature): return self.valid


class Adapter(CarrierAdapter):
    def __init__(self, verifier=None, result=None, error=None, circuit=None):
        super().__init__(AdapterCapabilities("crew-operations",frozenset({"crew.v1"}),
            frozenset({"publish_assignment"})),verifier or Verifier(),circuit)
        self.result=result;self.error=error;self.published=[]
    def _fetch(self,contract_version,cursor):
        return AdapterPage(({"id":"C1"},),"next",datetime.now(timezone.utc),contract_version)
    def _publish(self,command):
        self.published.append(command)
        if self.error:raise self.error
        return self.result or PublishResult(command.command_id,PublishStatus.ACKNOWLEDGED,
            "crew-ref-1",datetime.now(timezone.utc))


def command(**changes):
    values=dict(command_id="CMD-1",tenant_id="airline-1",deployment_id="DPL-1",
        recovery_id="REC-1",candidate_id="CAN-1",candidate_version=2,state_version=8,
        target_system="crew-operations",resource_type="crew",resource_id="IC-1",
        action="publish_assignment",payload={"flight_id":"AI421"},proposed_by="scheduler-1",
        requested_by="controller-1",approvals=(ApprovalEvidence("manager-1","duty-manager",
            datetime.now(timezone.utc)),),correlation_id="correlation-1",idempotency_key="publish-cmd-1",
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=5),signing_key_id="kms-key-1",signature="signed")
    values.update(changes);return DeploymentCommand(**values)


def test_contract_negotiation_and_read_page_are_explicit():
    adapter=Adapter()
    assert adapter.negotiate_contract({"crew.v1","crew.v2"})=="crew.v1"
    assert adapter.fetch("crew.v1").contract_version=="crew.v1"
    with pytest.raises(UnsupportedContract):adapter.negotiate_contract({"crew.v9"})


def test_signed_current_segregated_command_can_publish():
    adapter=Adapter();result=adapter.publish(command(),current_state_version=8)
    assert result.status is PublishStatus.ACKNOWLEDGED and result.source_system_reference=="crew-ref-1"
    assert len(adapter.published)==1


@pytest.mark.parametrize("changed",[
    {"state_version":7},{"target_system":"passenger-service"},{"action":"delete_roster"},
    {"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)},
    {"proposed_by":"manager-1"},{"requested_by":"manager-1"},
])
def test_unsafe_commands_are_rejected_before_carrier_call(changed):
    adapter=Adapter()
    with pytest.raises(AdapterSecurityError):adapter.publish(command(**changed),current_state_version=8)
    assert adapter.published==[]


def test_invalid_signature_is_rejected_before_carrier_call():
    adapter=Adapter(verifier=Verifier(False))
    with pytest.raises(AdapterSecurityError,match="signature"):adapter.publish(command(),8)


def test_timeout_and_dependency_failure_are_normalized_without_fake_ack():
    timed=Adapter(error=SourceTimeout("no acknowledgement")).publish(command(),8)
    failed=Adapter(error=RuntimeError("vendor leaked detail")).publish(command(),8)
    assert timed.status is PublishStatus.TIMED_OUT and timed.acknowledged_at is None
    assert failed.status is PublishStatus.REJECTED and failed.failure_detail=="RuntimeError"


def test_ack_without_source_reference_is_rejected():
    adapter=Adapter(result=PublishResult("CMD-1",PublishStatus.ACKNOWLEDGED,None,datetime.now(timezone.utc)))
    with pytest.raises(AdapterSecurityError,match="source-system reference"):adapter.publish(command(),8)


def test_circuit_breaker_opens_and_half_open_probe_can_recover():
    now=[0.0];circuit=CircuitBreaker(2,10,lambda:now[0]);adapter=Adapter(error=RuntimeError(),circuit=circuit)
    adapter.publish(command(),8);adapter.publish(command(),8)
    assert circuit.state=="open"
    from integrations.adapters.base import AdapterUnavailable
    with pytest.raises(AdapterUnavailable):adapter.publish(command(),8)
    now[0]=11;adapter.error=None
    assert adapter.publish(command(),8).status is PublishStatus.ACKNOWLEDGED and circuit.state=="closed"


def test_recursive_telemetry_redaction_removes_common_pii():
    value=redact_for_telemetry({"crew":{"name":"A","email":"a@x","id":"C1"},
        "parties":[{"pnr":"ABC123","status":"misconnected"}]})
    assert value["crew"]=={"name":"[REDACTED]","email":"[REDACTED]","id":"C1"}
    assert value["parties"][0]["pnr"]=="[REDACTED]"
