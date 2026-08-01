from pathlib import Path


SQL = (Path(__file__).parents[1] / "infrastructure" / "migrations" / "003_recovery_workflow_projections.sql").read_text()


def test_operational_workflow_projections_are_versioned_and_tenant_isolated():
    for table in (
        "recovery_projection", "candidate_artifact", "resource_hold_projection",
        "approval_projection", "deployment_projection", "deployment_command_projection",
        "partition_reconciliation_projection",
    ):
        assert f"CREATE TABLE {table}" in SQL
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in SQL
        assert f"tenant_isolation_{table}" in SQL


def test_holds_and_mutations_have_conflict_guards():
    assert "CREATE UNIQUE INDEX one_active_resource_hold" in SQL
    assert "UNIQUE (tenant_id, idempotency_key)" in SQL
    assert "candidate_version bigint NOT NULL" in SQL
    assert "state_version bigint NOT NULL" in SQL


def test_deployment_commands_preserve_partial_failure_states():
    for state in ("acknowledged", "rejected", "timed_out", "compensating", "compensated", "irreversible"):
        assert state in SQL
