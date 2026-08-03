"""Tenant-isolated Aurora readers for recovery, deployment and audit views."""

from __future__ import annotations

from datetime import datetime,timezone
import json
from typing import Any,Callable


class ProjectionNotFound(LookupError):pass


def _json(value):return value if isinstance(value,(dict,list)) else json.loads(value)


class OperationalReadRepository:
    def __init__(self,connection_factory:Callable[[],Any]):self.connection_factory=connection_factory
    def _read(self,tenant_id:str,operation:Callable[[Any],Any]):
        if not tenant_id:raise ValueError("tenant_id is required")
        connection=self.connection_factory()
        try:
            cursor=connection.cursor();cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)",(tenant_id,))
            result=operation(cursor);connection.commit();return result
        except Exception:connection.rollback();raise
        finally:connection.close()

    def recovery(self,tenant_id:str,recovery_id:str)->dict[str,Any]:
        def query(cursor):
            cursor.execute("SELECT state_version,snapshot,last_event_id,updated_at FROM recovery_workflow_snapshot WHERE tenant_id=%s AND recovery_id=%s",(tenant_id,recovery_id))
            row=cursor.fetchone()
            if row is None:raise ProjectionNotFound("recovery not found")
            return {"state_version":int(row[0]),"recovery":_json(row[1]),"last_event_id":str(row[2]),"updated_at":row[3]}
        return self._read(tenant_id,query)

    def candidates(self,tenant_id:str,recovery_id:str,now:datetime|None=None)->list[dict[str,Any]]:
        now=now or datetime.now(timezone.utc)
        def query(cursor):
            cursor.execute("SELECT candidate_id,candidate_version,input_snapshot_id,solver_tier,solver_version,ruleset_version,objective_version,content_sha256,s3_object_version_id,expires_at,created_at FROM candidate_artifact WHERE tenant_id=%s AND recovery_id=%s ORDER BY created_at DESC",(tenant_id,recovery_id))
            return [{"candidate_id":str(r[0]),"candidate_version":int(r[1]),"input_snapshot_id":str(r[2]),
                "solver_tier":r[3],"solver_version":r[4],"ruleset_version":r[5],"objective_version":r[6],
                "content_sha256":r[7],"s3_object_version_id":r[8],"expires_at":r[9],"created_at":r[10],
                "expired":r[9]<=now} for r in cursor.fetchall()]
        return self._read(tenant_id,query)

    def deployment(self,tenant_id:str,deployment_id:str)->dict[str,Any]:
        def query(cursor):
            cursor.execute("SELECT recovery_id,candidate_id,candidate_version,status,state_version,correlation_id,requested_by,requested_at,completed_at FROM deployment_projection WHERE tenant_id=%s AND deployment_id=%s",(tenant_id,deployment_id))
            row=cursor.fetchone()
            if row is None:raise ProjectionNotFound("deployment not found")
            cursor.execute("SELECT command_id,resource_type,resource_id,target_system,action,status,required,reversible,attempt_count,source_system_reference,failure_code,last_error,published_at,acknowledged_at FROM deployment_command_projection WHERE tenant_id=%s AND deployment_id=%s ORDER BY command_id",(tenant_id,deployment_id))
            commands=[{"command_id":str(r[0]),"resource_type":r[1],"resource_id":r[2],"target_system":r[3],
                "action":r[4],"status":r[5],"required":bool(r[6]),"reversible":bool(r[7]),"attempt_count":int(r[8]),
                "source_system_reference":r[9],"failure_code":r[10],"last_error":r[11],"published_at":r[12],
                "acknowledged_at":r[13]} for r in cursor.fetchall()]
            required=[item for item in commands if item["required"]]
            complete=bool(required) and all(item["status"]=="acknowledged" for item in required)
            return {"deployment_id":deployment_id,"recovery_id":str(row[0]),"candidate_id":str(row[1]),
                "candidate_version":int(row[2]),"status":row[3],"state_version":int(row[4]),
                "correlation_id":str(row[5]),"requested_by":row[6],"requested_at":row[7],"completed_at":row[8],
                "commands":commands,"complete":complete,"partial":row[3]=="partial"}
        return self._read(tenant_id,query)

    def audit(self,tenant_id:str,*,recovery_id:str|None=None,after_event_id:str|None=None,
              limit:int=200)->list[dict[str,Any]]:
        if limit<1 or limit>1000:raise ValueError("audit limit must be between 1 and 1000")
        def query(cursor):
            after_recorded=None
            if after_event_id:
                cursor.execute("SELECT recorded_at FROM operational_event WHERE tenant_id=%s AND event_id=%s",(tenant_id,after_event_id))
                row=cursor.fetchone()
                if row is None:raise ProjectionNotFound("audit cursor not found")
                after_recorded=row[0]
            clauses=["tenant_id=%s"];parameters:[Any]=[tenant_id]
            if recovery_id:clauses.extend(["aggregate_type='recovery'","aggregate_id=%s"]);parameters.append(recovery_id)
            if after_recorded is not None:clauses.append("recorded_at>%s");parameters.append(after_recorded)
            parameters.append(limit)
            cursor.execute("SELECT event_id,aggregate_type,aggregate_id,aggregate_version,event_type,recorded_at,correlation_id,causation_id,actor_subject,payload,payload_sha256 FROM operational_event WHERE "+" AND ".join(clauses)+" ORDER BY recorded_at,event_id LIMIT %s",tuple(parameters))  # nosec B608 - clause fragments are fixed constants and values remain parameterized
            return [{"event_id":str(r[0]),"aggregate_type":r[1],"aggregate_id":r[2],"aggregate_version":int(r[3]),
                "event_type":r[4],"recorded_at":r[5],"correlation_id":str(r[6]),"causation_id":str(r[7]) if r[7] else None,
                "actor_subject":r[8],"payload":_json(r[9]),"payload_sha256":r[10]} for r in cursor.fetchall()]
        return self._read(tenant_id,query)
