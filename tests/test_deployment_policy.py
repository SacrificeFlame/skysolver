import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_frontend_dependencies_are_exactly_pinned():
    package = json.loads((ROOT / "deployment/frontend/package.json").read_text(encoding="utf-8"))
    versions = [*package["dependencies"].values(), *package["devDependencies"].values()]
    assert versions
    assert all(version != "latest" for version in versions)
    assert all(not version.startswith(("^", "~", ">", "<", "*")) for version in versions)


def test_kubernetes_worker_is_non_root_read_only_and_digest_pinned():
    manifest = (ROOT / "deployment/k8s/worker-deployment.yaml").read_text(encoding="utf-8")
    assert "runAsNonRoot: true" in manifest
    assert "readOnlyRootFilesystem: true" in manifest
    assert "allowPrivilegeEscalation: false" in manifest
    assert "@sha256:" in manifest
    assert ":latest" not in manifest


def test_terraform_baseline_cannot_enable_carrier_writes():
    variables = (ROOT / "infrastructure/terraform/variables.tf").read_text(encoding="utf-8")
    assert 'variable "carrier_writes_enabled"' in variables
    assert "condition     = var.carrier_writes_enabled == false" in variables


def test_aurora_event_schema_has_required_safety_primitives():
    migration = (ROOT / "infrastructure/migrations/001_operational_event_store.sql").read_text(encoding="utf-8")
    assert "UNIQUE (tenant_id, aggregate_type, aggregate_id, aggregate_version)" in migration
    assert "CREATE TABLE transactional_outbox" in migration
    assert "CREATE TABLE consumed_event" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
