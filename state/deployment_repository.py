"""Aurora repository for restart-safe deployment command orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable

from state.postgres_event_store import OptimisticConcurrencyError


class DeploymentPersistenceError(RuntimeError): pass


@dataclass(frozen=True)
class ClaimedCommand:
    tenant_id: str
    deployment_id: str
    command_id: str
    command_idempotency_key: str
    resource_type: str
    resource_id: str
    target_system: str
    action: str
    payload: dict[str, Any]
    state_version: int
    attempt_count: int


@dataclass(frozen=True)
class DeploymentTransition:
    deployment_id: str
    command_id: str
    command_status: str
    deployment_status: str
    state_version: int
    replayed: bool = False


class DurableDeploymentRepository:
    def __init__(self, connection_factory: Callable[[], Any]):
        self._connection_factory = connection_factory

    def claim_commands(self, worker_id: str, limit: int = 50) -> list[ClaimedCommand]:
        if not worker_id or limit < 1 or limit > 500:
            raise ValueError("worker_id and a limit between 1 and 500 are required")
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "WITH claimable AS (SELECT tenant_id,deployment_id,command_id "
                "FROM deployment_command_projection WHERE status='queued' AND claimed_at IS NULL "
                "AND next_attempt_at<=clock_timestamp() ORDER BY next_attempt_at,command_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s) "
                "UPDATE deployment_command_projection c SET claimed_at=clock_timestamp(),claimed_by=%s "
                "FROM claimable q WHERE c.tenant_id=q.tenant_id AND c.deployment_id=q.deployment_id "
                "AND c.command_id=q.command_id RETURNING c.tenant_id,c.deployment_id,c.command_id,"
                "c.command_idempotency_key,c.resource_type,c.resource_id,c.target_system,c.action,"
                "c.payload,c.deployment_state_version,c.attempt_count",
                (limit, worker_id),
            )
            rows = cursor.fetchall()
            connection.commit()
            return [ClaimedCommand(
                tenant_id=str(row[0]), deployment_id=str(row[1]), command_id=str(row[2]),
                command_idempotency_key=str(row[3]), resource_type=str(row[4]), resource_id=str(row[5]),
                target_system=str(row[6]), action=str(row[7]),
                payload=row[8] if isinstance(row[8], dict) else json.loads(row[8]),
                state_version=int(row[9]), attempt_count=int(row[10]),
            ) for row in rows]
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def mark_published(self, *, tenant_id: str, deployment_id: str, command_id: str,
                       worker_id: str, expected_version: int, source_reference: str) -> DeploymentTransition:
        if not source_reference:
            raise ValueError("publication requires a source-system reference")
        return self._transition(tenant_id=tenant_id,deployment_id=deployment_id,command_id=command_id,
            worker_id=worker_id,expected_version=expected_version,target_status="published",
            source_reference=source_reference,failure_code=None,failure_detail=None)

    def acknowledge(self, *, tenant_id: str, deployment_id: str, command_id: str,
                    expected_version: int, accepted: bool, source_reference: str | None,
                    failure_code: str | None = None, failure_detail: str | None = None) -> DeploymentTransition:
        if accepted and not source_reference:
            raise ValueError("accepted command requires source-system evidence")
        if not accepted and not failure_code:
            raise ValueError("rejected command requires a failure code")
        return self._transition(tenant_id=tenant_id,deployment_id=deployment_id,command_id=command_id,
            worker_id=None,expected_version=expected_version,
            target_status="acknowledged" if accepted else "rejected",source_reference=source_reference,
            failure_code=failure_code,failure_detail=failure_detail)

    def timeout(self, *, tenant_id: str, deployment_id: str, command_id: str,
                expected_version: int) -> DeploymentTransition:
        return self._transition(tenant_id=tenant_id,deployment_id=deployment_id,command_id=command_id,
            worker_id=None,expected_version=expected_version,target_status="timed_out",
            source_reference=None,failure_code="ACK_TIMEOUT",failure_detail="Source acknowledgement deadline exceeded")

    def _transition(self, *, tenant_id: str, deployment_id: str, command_id: str,
                    worker_id: str | None, expected_version: int, target_status: str,
                    source_reference: str | None, failure_code: str | None,
                    failure_detail: str | None) -> DeploymentTransition:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)", (tenant_id,))
            cursor.execute(
                "SELECT state_version,status FROM deployment_projection WHERE tenant_id=%s "
                "AND deployment_id=%s FOR UPDATE", (tenant_id,deployment_id),
            )
            deployment = cursor.fetchone()
            if deployment is None: raise DeploymentPersistenceError("deployment not found")
            current_version,current_deployment_status=int(deployment[0]),str(deployment[1])
            if current_version != expected_version:
                raise OptimisticConcurrencyError(f"expected deployment version {expected_version}, found {current_version}")
            cursor.execute(
                "SELECT status,source_system_reference,failure_code,claimed_by FROM deployment_command_projection "
                "WHERE tenant_id=%s AND deployment_id=%s AND command_id=%s FOR UPDATE",
                (tenant_id,deployment_id,command_id),
            )
            command = cursor.fetchone()
            if command is None: raise DeploymentPersistenceError("deployment command not found")
            current_status,current_reference,current_failure,claimed_by=command
            if str(current_status)==target_status and current_reference==source_reference and current_failure==failure_code:
                connection.commit()
                return DeploymentTransition(deployment_id,command_id,target_status,current_deployment_status,
                                            current_version,True)
            allowed={"published":{"queued"},"acknowledged":{"published"},"rejected":{"published"},
                     "timed_out":{"published"}}
            if str(current_status) not in allowed[target_status]:
                raise DeploymentPersistenceError(f"cannot transition {current_status} to {target_status}")
            if target_status=="published" and claimed_by != worker_id:
                raise DeploymentPersistenceError("deployment command claim is stale or owned by another worker")

            new_version=current_version+1
            cursor.execute(
                "UPDATE deployment_command_projection SET status=%s,source_system_reference=%s,"
                "failure_code=%s,last_error=%s,claimed_at=NULL,claimed_by=NULL,attempt_count=attempt_count+%s,"
                "published_at=CASE WHEN %s='published' THEN clock_timestamp() ELSE published_at END,"
                "acknowledged_at=CASE WHEN %s IN ('acknowledged','rejected') THEN clock_timestamp() ELSE acknowledged_at END,"
                "deployment_state_version=%s WHERE tenant_id=%s AND deployment_id=%s AND command_id=%s",
                (target_status,source_reference,failure_code,failure_detail,1 if target_status=="published" else 0,
                 target_status,target_status,new_version,tenant_id,deployment_id,command_id),
            )
            cursor.execute(
                "SELECT count(*) FILTER (WHERE required),"
                "count(*) FILTER (WHERE required AND status='acknowledged'),"
                "count(*) FILTER (WHERE required AND status IN ('rejected','timed_out')) "
                "FROM deployment_command_projection WHERE tenant_id=%s AND deployment_id=%s",
                (tenant_id,deployment_id),
            )
            total,acknowledged,failed=map(int,cursor.fetchone())
            if total > 0 and acknowledged == total:
                deployment_status="complete"
            elif failed and acknowledged:
                deployment_status="partial"
            elif failed:
                deployment_status="failed"
            else:
                deployment_status="publishing"
            cursor.execute(
                "UPDATE deployment_projection SET status=%s,state_version=%s,"
                "completed_at=CASE WHEN %s='complete' THEN clock_timestamp() ELSE NULL END "
                "WHERE tenant_id=%s AND deployment_id=%s AND state_version=%s",
                (deployment_status,new_version,deployment_status,tenant_id,deployment_id,current_version),
            )
            if cursor.rowcount != 1:
                raise OptimisticConcurrencyError("deployment changed during command transition")
            connection.commit()
            return DeploymentTransition(deployment_id,command_id,target_status,deployment_status,new_version)
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def release_claim(self, *, tenant_id: str, deployment_id: str, command_id: str,
                      worker_id: str, error: str, attempt_count: int) -> None:
        connection=self._connection_factory()
        try:
            cursor=connection.cursor();cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)",(tenant_id,))
            delay=min(300,2**min(attempt_count+1,8))
            cursor.execute(
                "UPDATE deployment_command_projection SET claimed_at=NULL,claimed_by=NULL,last_error=%s,"
                "next_attempt_at=clock_timestamp()+(%s * interval '1 second') WHERE tenant_id=%s "
                "AND deployment_id=%s AND command_id=%s AND claimed_by=%s AND status='queued'",
                (error[:2000],delay,tenant_id,deployment_id,command_id,worker_id),
            )
            if cursor.rowcount != 1: raise DeploymentPersistenceError("deployment command claim is missing")
            connection.commit()
        except Exception:
            connection.rollback();raise
        finally:connection.close()
