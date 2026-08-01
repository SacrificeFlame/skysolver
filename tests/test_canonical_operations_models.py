from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from core.canonical import (
    AirportRef, ApprovalRecord, DeploymentAcknowledgement, DutyPeriod, FreshnessState,
    Pairing, PassengerParty, Provenance, RecoveryPlan, RulesetReference, TemporalContext,
)


NOW = datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc)


def provenance(record_id="record-1"):
    return Provenance(source_system="carrier-fixture",source_record_id=record_id,
        source_timestamp=NOW,ingestion_timestamp=NOW+timedelta(seconds=1),contract_version="canonical.v1")


def base(record_id):
    return dict(canonical_id=record_id,source_system_id=record_id,tenant_id="airline-1",
        version=1,provenance=provenance(record_id),freshness=FreshnessState.CURRENT)


def instant(hour, minute=0):
    utc=datetime(2026,8,1,hour,minute,tzinfo=timezone.utc);local=utc.astimezone(ZoneInfo("Asia/Kolkata"))
    return TemporalContext(utc_instant=utc,local_airport_time=local,iana_timezone="Asia/Kolkata",
        operating_date=local.date())


DEL=AirportRef(iata_code="DEL",iana_timezone="Asia/Kolkata")


def duty(identifier,report,release):
    return DutyPeriod(**base(identifier),crew_id="IC-1",report=report,release=release,
        flight_segment_ids=("AI421",),duty_kind="flight_duty")


def test_pairing_rejects_overlapping_duties():
    first=duty("D1",instant(4),instant(7));second=duty("D2",instant(6),instant(9))
    with pytest.raises(ValidationError,match="cannot overlap"):
        Pairing(**base("P1"),pairing_number="PAIR-1",crew_role="captain",base_airport=DEL,duties=(first,second))


def test_reaccommodated_passenger_party_requires_confirmed_inventory():
    with pytest.raises(ValidationError,match="confirmed inventory"):
        PassengerParty(**base("PNR-1"),pnr_reference="PNR-1",passenger_count=3,
            itinerary_segment_ids=("AI421",),disruption_status="reaccommodated")


def test_selected_candidate_must_belong_to_plan():
    with pytest.raises(ValidationError,match="belong"):
        RecoveryPlan(**base("REC-1"),disruption_id="DSP-1",input_snapshot_id="SNP-1",
            partition_ids=("DEL",),candidate_ids=("CAN-1",),selected_candidate_id="CAN-2",
            status="awaiting_review",state_version=4)


def test_acknowledged_deployment_command_requires_source_evidence():
    with pytest.raises(ValidationError,match="source evidence"):
        DeploymentAcknowledgement(**base("ACK-1"),deployment_id="DPL-1",command_id="CMD-1",
            resource_type="crew",resource_id="IC-1",status="acknowledged")


def test_ruleset_activation_requires_four_eyes_evidence():
    with pytest.raises(ValidationError,match="two distinct approvals"):
        RulesetReference(**base("RULE-1"),ruleset_name="DGCA FDTL",ruleset_version="2026.08",
            effective_from=NOW,package_sha256="a"*64,signing_key_id="kms-1",
            approval_references=("approval-1","approval-1"))


def test_approval_preserves_candidate_rules_and_state_versions():
    approval=ApprovalRecord(**base("APR-1"),recovery_id="REC-1",candidate_id="CAN-1",
        candidate_version=3,actor_subject="manager-1",actor_role="duty-manager",
        reason="Reviewed legality trace",approved_at=NOW,ruleset_version="2026.08",state_version=9)
    assert approval.candidate_version==3 and approval.state_version==9
