# Operational state migrations

`001_operational_event_store.sql` establishes the Aurora PostgreSQL write model,
transactional outbox, idempotent-consumer ledger and immutable snapshot index.

The application must set `skysolver.tenant_id` for every transaction. Database
roles used by the application must not have `BYPASSRLS`. An event append updates
`aggregate_stream`, inserts `operational_event`, and inserts its outbox row in
one database transaction after locking the aggregate row and checking the
expected version. The MSK publisher marks `published_at` only after broker ACK.

S3 objects referenced by `input_snapshot` must be written to a versioned bucket
with Object Lock before the row commits. This migration does not claim that the
current local demo uses Aurora or MSK; activation is an environment exit gate.

`003_recovery_workflow_projections.sql` adds rebuildable recovery, candidate,
resource-hold, approval, deployment-command and cross-partition reconciliation
projections. It preserves partial command outcomes and prevents two active holds
on the same tenant resource. These are projections of the event stream, not a
second source of truth.
