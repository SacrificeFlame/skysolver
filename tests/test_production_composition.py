import pytest
from fastapi.testclient import TestClient

from deployment.production_api import create_app
from deployment.production_composition import (
    DependencyProbe, IncompleteProductionComposition, RuntimeDependencyRegistry, aurora_probe,
)
from deployment.runtime_config import UnsafeRuntimeConfiguration


class Connection:
    def __init__(self,row=(1,)):self.row=row;self.commits=self.rollbacks=self.closed=0
    def cursor(self):return self
    def execute(self,sql):self.sql=sql
    def fetchone(self):return self.row
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1
    def close(self):self.closed+=1


class DurableStore:
    durable_authoritative=True


def production_environment(monkeypatch):
    values={"SKYSOLVER_RUNTIME_MODE":"shadow-production",
        "SKYSOLVER_PERSISTENCE_BACKEND":"aurora-postgresql","SKYSOLVER_EVENT_BACKEND":"amazon-msk",
        "SKYSOLVER_DATABASE_URL":"postgresql://iam@cluster/db","MSK_BOOTSTRAP_SERVERS":"broker:9098"}
    for key,value in values.items():monkeypatch.setenv(key,value)


def registry(**overrides):
    readiness={"aurora":True,"msk":True,"validation_service":True,"artifact_store":True,"required_adapters":True}
    readiness.update(overrides)
    return RuntimeDependencyRegistry([DependencyProbe(name,lambda value=value:value) for name,value in readiness.items()])


def test_registry_refuses_missing_or_non_authoritative_required_probe():
    with pytest.raises(IncompleteProductionComposition,match="missing probes"):
        RuntimeDependencyRegistry([DependencyProbe("aurora",lambda:True)]).assert_configured()
    probes=[DependencyProbe(name,lambda:True,authoritative=name!="required_adapters")
            for name in ("aurora","msk","validation_service","artifact_store","required_adapters")]
    with pytest.raises(IncompleteProductionComposition,match="non-authoritative"):
        RuntimeDependencyRegistry(probes).assert_configured()


def test_production_api_refuses_durable_store_without_dependency_registry(monkeypatch):
    production_environment(monkeypatch)
    with pytest.raises(UnsafeRuntimeConfiguration,match="dependency registry"):
        create_app(DurableStore())


def test_readiness_is_503_when_any_required_dependency_is_down(monkeypatch):
    production_environment(monkeypatch)
    response=TestClient(create_app(DurableStore(),runtime_health=registry(msk=False))).get("/api/v1/health/ready")
    assert response.status_code==503 and response.json()["status"]=="not_ready"
    assert next(item for item in response.json()["dependencies"] if item["name"]=="msk")["ready"] is False


def test_readiness_is_authoritative_only_when_every_required_probe_passes(monkeypatch):
    production_environment(monkeypatch)
    response=TestClient(create_app(DurableStore(),runtime_health=registry())).get("/api/v1/health/ready")
    assert response.status_code==200 and response.json()["ready"] is True
    assert response.json()["authoritative"] is True


def test_aurora_probe_commits_health_query_and_closes_connection():
    connection=Connection();assert aurora_probe(lambda:connection)() is True
    assert connection.sql=="SELECT 1" and connection.commits==1 and connection.closed==1
