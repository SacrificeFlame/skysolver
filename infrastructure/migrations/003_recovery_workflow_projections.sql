BEGIN;

CREATE TABLE recovery_projection (
    tenant_id text NOT NULL,
    recovery_id uuid NOT NULL,
    disruption_id text NOT NULL,
    partition_id text NOT NULL,
    status text NOT NULL,
    stage text NOT NULL,
    state_version bigint NOT NULL CHECK (state_version > 0),
    input_snapshot_id uuid,
    selected_candidate_id uuid,
    proposed_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, recovery_id)
);

CREATE TABLE candidate_artifact (
    tenant_id text NOT NULL,
    candidate_id uuid NOT NULL,
    recovery_id uuid NOT NULL,
    candidate_version bigint NOT NULL CHECK (candidate_version > 0),
    input_snapshot_id uuid NOT NULL,
    solver_tier text NOT NULL,
    solver_version text NOT NULL,
    ruleset_version text NOT NULL,
    objective_version text NOT NULL,
    content_sha256 char(64) NOT NULL,
    s3_object_version_id text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, candidate_id, candidate_version),
    FOREIGN KEY (tenant_id, recovery_id) REFERENCES recovery_projection (tenant_id, recovery_id)
);

CREATE TABLE resource_hold_projection (
    tenant_id text NOT NULL,
    hold_id uuid NOT NULL,
    recovery_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    candidate_version bigint NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('active','released','expired','committed')),
    held_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    released_at timestamptz,
    PRIMARY KEY (tenant_id, hold_id, resource_type, resource_id),
    FOREIGN KEY (tenant_id, recovery_id) REFERENCES recovery_projection (tenant_id, recovery_id)
);
CREATE UNIQUE INDEX one_active_resource_hold
    ON resource_hold_projection (tenant_id, resource_type, resource_id)
    WHERE status = 'active';

CREATE TABLE approval_projection (
    tenant_id text NOT NULL,
    approval_id uuid NOT NULL,
    recovery_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    candidate_version bigint NOT NULL,
    actor_subject text NOT NULL,
    actor_role text NOT NULL,
    approval_type text NOT NULL,
    reason text NOT NULL CHECK (length(reason) >= 3),
    ruleset_version text NOT NULL,
    state_version bigint NOT NULL,
    approved_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (tenant_id, approval_id),
    FOREIGN KEY (tenant_id, recovery_id) REFERENCES recovery_projection (tenant_id, recovery_id)
);

CREATE TABLE deployment_projection (
    tenant_id text NOT NULL,
    deployment_id uuid NOT NULL,
    recovery_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    candidate_version bigint NOT NULL,
    status text NOT NULL,
    state_version bigint NOT NULL CHECK (state_version > 0),
    idempotency_key text NOT NULL,
    correlation_id uuid NOT NULL,
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL,
    completed_at timestamptz,
    PRIMARY KEY (tenant_id, deployment_id),
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, recovery_id) REFERENCES recovery_projection (tenant_id, recovery_id)
);

CREATE TABLE deployment_command_projection (
    tenant_id text NOT NULL,
    deployment_id uuid NOT NULL,
    command_id uuid NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    target_system text NOT NULL,
    action text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','published','acknowledged','rejected','timed_out','compensating','compensated','irreversible')),
    reversible boolean NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    source_system_reference text,
    last_error text,
    published_at timestamptz,
    acknowledged_at timestamptz,
    PRIMARY KEY (tenant_id, deployment_id, command_id),
    FOREIGN KEY (tenant_id, deployment_id) REFERENCES deployment_projection (tenant_id, deployment_id)
);

CREATE TABLE partition_reconciliation_projection (
    tenant_id text NOT NULL,
    saga_id uuid NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    source_partition text NOT NULL,
    destination_partition text NOT NULL,
    status text NOT NULL,
    source_acknowledged boolean NOT NULL DEFAULT false,
    destination_acknowledged boolean NOT NULL DEFAULT false,
    state_version bigint NOT NULL CHECK (state_version > 0),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, saga_id)
);

ALTER TABLE recovery_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE resource_hold_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployment_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployment_command_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE partition_reconciliation_projection ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_recovery_projection ON recovery_projection USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_candidate_artifact ON candidate_artifact USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_resource_hold_projection ON resource_hold_projection USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_approval_projection ON approval_projection USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_deployment_projection ON deployment_projection USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_deployment_command_projection ON deployment_command_projection USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_partition_reconciliation_projection ON partition_reconciliation_projection USING (tenant_id = current_setting('skysolver.tenant_id', true));

COMMIT;
