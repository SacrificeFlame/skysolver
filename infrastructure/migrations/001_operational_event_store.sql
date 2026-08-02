BEGIN;

CREATE TABLE aggregate_stream (
    tenant_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    current_version bigint NOT NULL DEFAULT 0 CHECK (current_version >= 0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, aggregate_type, aggregate_id)
);

CREATE TABLE operational_event (
    event_id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    aggregate_version bigint NOT NULL CHECK (aggregate_version > 0),
    partition_key text NOT NULL,
    event_type text NOT NULL,
    schema_version text NOT NULL,
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    correlation_id uuid NOT NULL,
    causation_id uuid,
    actor_subject text NOT NULL,
    payload jsonb NOT NULL,
    payload_sha256 char(64) NOT NULL,
    UNIQUE (tenant_id, aggregate_type, aggregate_id, aggregate_version)
);

CREATE INDEX operational_event_partition_order
    ON operational_event (tenant_id, partition_key, recorded_at, event_id);
CREATE INDEX operational_event_correlation
    ON operational_event (tenant_id, correlation_id);

CREATE TABLE transactional_outbox (
    event_id uuid PRIMARY KEY REFERENCES operational_event(event_id),
    tenant_id text NOT NULL,
    topic text NOT NULL,
    partition_key text NOT NULL,
    envelope jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_error text
);

CREATE INDEX transactional_outbox_pending
    ON transactional_outbox (next_attempt_at, created_at)
    WHERE published_at IS NULL;

CREATE TABLE consumer_checkpoint (
    tenant_id text NOT NULL,
    consumer_group text NOT NULL,
    topic text NOT NULL,
    partition_number integer NOT NULL CHECK (partition_number >= 0),
    kafka_offset bigint NOT NULL CHECK (kafka_offset >= 0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, consumer_group, topic, partition_number)
);

CREATE TABLE consumed_event (
    tenant_id text NOT NULL,
    consumer_group text NOT NULL,
    event_id uuid NOT NULL,
    consumed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, consumer_group, event_id)
);

CREATE TABLE input_snapshot (
    snapshot_id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    recovery_id uuid NOT NULL,
    state_version bigint NOT NULL CHECK (state_version > 0),
    ruleset_version text NOT NULL,
    objective_version text NOT NULL,
    captured_at timestamptz NOT NULL,
    content_sha256 char(64) NOT NULL,
    s3_object_version_id text NOT NULL,
    kms_key_id text NOT NULL,
    UNIQUE (tenant_id, recovery_id, state_version)
);

ALTER TABLE aggregate_stream ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactional_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE consumer_checkpoint ENABLE ROW LEVEL SECURITY;
ALTER TABLE consumed_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE input_snapshot ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_aggregate_stream ON aggregate_stream
    USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_operational_event ON operational_event
    USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_transactional_outbox ON transactional_outbox
    USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_consumer_checkpoint ON consumer_checkpoint
    USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_consumed_event ON consumed_event
    USING (tenant_id = current_setting('skysolver.tenant_id', true));
CREATE POLICY tenant_isolation_input_snapshot ON input_snapshot
    USING (tenant_id = current_setting('skysolver.tenant_id', true));

COMMIT;
