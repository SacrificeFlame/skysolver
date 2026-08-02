BEGIN;

ALTER TABLE deployment_command_projection
    ADD COLUMN required boolean NOT NULL DEFAULT true,
    ADD COLUMN payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN command_idempotency_key text,
    ADD COLUMN deployment_state_version bigint NOT NULL DEFAULT 1,
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN claimed_by text,
    ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ADD COLUMN failure_code text;

UPDATE deployment_command_projection
SET command_idempotency_key = deployment_id::text || ':' || command_id::text
WHERE command_idempotency_key IS NULL;

ALTER TABLE deployment_command_projection
    ALTER COLUMN command_idempotency_key SET NOT NULL,
    ADD CONSTRAINT deployment_command_idempotency
        UNIQUE (tenant_id, target_system, command_idempotency_key);

CREATE INDEX deployment_command_claimable
    ON deployment_command_projection (next_attempt_at, command_id)
    WHERE status = 'queued' AND claimed_at IS NULL;

COMMIT;
