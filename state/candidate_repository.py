"""Aurora index for immutable candidate artifacts."""

from __future__ import annotations

import json
from typing import Any, Callable

from core.candidate_lifecycle import ImmutableCandidate


class CandidateRepositoryConflict(RuntimeError): pass


class PostgresCandidateRepository:
    def __init__(self,connection_factory:Callable[[],Any]):self.connection_factory=connection_factory
    def insert(self,candidate:ImmutableCandidate)->None:
        draft=candidate.draft;connection=self.connection_factory()
        try:
            cursor=connection.cursor();cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)",(draft.tenant_id,))
            cursor.execute(
                "INSERT INTO candidate_artifact (tenant_id,candidate_id,recovery_id,candidate_version,"
                "input_snapshot_id,solver_tier,solver_version,ruleset_version,objective_version,content_sha256,"
                "s3_object_version_id,expires_at,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING candidate_id",
                (draft.tenant_id,candidate.candidate_id,draft.recovery_id,candidate.candidate_version,
                 draft.input_snapshot_id,draft.solver_tier,draft.solver_version,draft.ruleset_version,
                 draft.objective_version,candidate.content_sha256,candidate.artifact.version_id,
                 draft.expires_at,candidate.created_at))
            if cursor.fetchone() is None:raise CandidateRepositoryConflict("candidate artifact already exists")
            connection.commit()
        except Exception:connection.rollback();raise
        finally:connection.close()
