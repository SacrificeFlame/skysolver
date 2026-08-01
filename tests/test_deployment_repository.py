import json
from pathlib import Path

import pytest

from state.deployment_repository import DurableDeploymentRepository, DeploymentPersistenceError
from state.postgres_event_store import OptimisticConcurrencyError


class Cursor:
    def __init__(self,ones=None,all_rows=None):
        self.ones=list(ones or []);self.all_rows=list(all_rows or []);self.executed=[];self.rowcount=1
    def execute(self,sql,parameters=()):self.executed.append((" ".join(sql.split()),parameters))
    def fetchone(self):return self.ones.pop(0) if self.ones else None
    def fetchall(self):return self.all_rows
class Connection:
    def __init__(self,cursor):self.c=cursor;self.commits=self.rollbacks=self.closed=0
    def cursor(self):return self.c
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1
    def close(self):self.closed+=1


def test_claim_uses_skip_locked_and_returns_stable_idempotency_key():
    row=("airline-1","DPL-1","CMD-1","DPL-1:CMD-1","crew","IC-1","crew-operations",
         "publish_assignment",json.dumps({"flight":"AI421"}),4,0)
    cursor=Cursor(all_rows=[row]);connection=Connection(cursor)
    commands=DurableDeploymentRepository(lambda:connection).claim_commands("publisher-1")
    assert commands[0].command_idempotency_key=="DPL-1:CMD-1" and commands[0].payload["flight"]=="AI421"
    assert "FOR UPDATE SKIP LOCKED" in cursor.executed[0][0] and connection.commits==1


@pytest.mark.parametrize("counts,expected",[((2,2,0),"complete"),((3,1,1),"partial"),
                                               ((2,0,1),"failed"),((2,1,0),"publishing")])
def test_deployment_status_is_derived_from_required_ack_counts(counts,expected):
    cursor=Cursor(ones=[(7,"publishing"),("published",None,None,None),counts]);connection=Connection(cursor)
    result=DurableDeploymentRepository(lambda:connection).acknowledge(tenant_id="airline-1",
        deployment_id="DPL-1",command_id="CMD-1",expected_version=7,accepted=expected!="failed",
        source_reference="source-1" if expected!="failed" else None,
        failure_code=None if expected!="failed" else "SOURCE_REJECTED")
    assert result.deployment_status==expected and result.state_version==8
    if expected=="complete":
        assert "THEN clock_timestamp()" in cursor.executed[-1][0]


def test_stale_deployment_version_rolls_back_before_command_update():
    cursor=Cursor(ones=[(9,"publishing")]);connection=Connection(cursor)
    with pytest.raises(OptimisticConcurrencyError):
        DurableDeploymentRepository(lambda:connection).timeout(tenant_id="airline-1",
            deployment_id="DPL-1",command_id="CMD-1",expected_version=8)
    assert connection.rollbacks==1
    assert not any("UPDATE deployment_command_projection SET status" in sql for sql,_ in cursor.executed)


def test_published_transition_requires_active_worker_claim():
    cursor=Cursor(ones=[(2,"queued"),("queued",None,None,"another-worker")]);connection=Connection(cursor)
    with pytest.raises(DeploymentPersistenceError,match="owned by another"):
        DurableDeploymentRepository(lambda:connection).mark_published(tenant_id="airline-1",
            deployment_id="DPL-1",command_id="CMD-1",worker_id="publisher-1",
            expected_version=2,source_reference="adapter-ref")


def test_duplicate_ack_is_replayed_without_advancing_version():
    cursor=Cursor(ones=[(8,"complete"),("acknowledged","source-1",None,None)]);connection=Connection(cursor)
    result=DurableDeploymentRepository(lambda:connection).acknowledge(tenant_id="airline-1",
        deployment_id="DPL-1",command_id="CMD-1",expected_version=8,accepted=True,
        source_reference="source-1")
    assert result.replayed and result.state_version==8 and connection.commits==1


def test_migration_adds_claiming_and_per_target_idempotency():
    sql=Path("infrastructure/migrations/005_durable_deployment_commands.sql").read_text(encoding="utf-8")
    assert "claimed_at" in sql and "command_idempotency_key" in sql
    assert "UNIQUE (tenant_id, target_system, command_idempotency_key)" in sql
    assert "WHERE status = 'queued' AND claimed_at IS NULL" in sql
