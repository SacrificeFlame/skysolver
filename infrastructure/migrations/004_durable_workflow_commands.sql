BEGIN;

CREATE TABLE recovery_workflow_snapshot (
    tenant_id text NOT NULL,
    recovery_id text NOT NULL,
    state_version bigint NOT NULL CHECK (state_version > 0),
    snapshot jsonb NOT NULL,
    last_event_id uuid NOT NULL REFERENCES operational_event(event_id),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, recovery_id)
);

CREATE TABLE workflow_command (
    tenant_id text NOT NULL,
    idempotency_key text NOT NULL,
    recovery_id text NOT NULL,
    command_type text NOT NULL,
    command_sha256 char(64) NOT NULL,
    status text NOT NULL CHECK (status IN ('processing', 'completed')),
    event_id uuid REFERENCES operational_event(event_id),
    state_version bigint,
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    PRIMARY KEY (tenant_id, idempotency_key),
    CHECK (
        (status = 'processing' AND event_id IS NULL AND state_version IS NULL AND response IS NULL AND completed_at IS NULL)
        OR
        (status = 'completed' AND event_id IS NOT NULL AND state_version IS NOT NULL AND response IS NOT NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX workflow_command_recovery
    ON workflow_command (tenant_id, recovery_id, created_at);

ALTER TABLE recovery_workflow_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_command ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_recovery_workflow_snapshot ON recovery_workflow_snapshot
    USING (tenant_id = current_setting('skysolver.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_workflow_command ON workflow_command
    USING (tenant_id = current_setting('skysolver.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('skysolver.tenant_id', true));

COMMIT;
