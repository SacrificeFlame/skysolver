import pytest

from deployment.runtime_config import RuntimeMode, UnsafeRuntimeConfiguration, load_runtime_configuration
from deployment.production_api import create_app


def test_development_defaults_to_contained_local_runtime():
    config = load_runtime_configuration({})
    assert config.mode is RuntimeMode.DEVELOPMENT
    assert config.persistence_backend == "local-json"
    assert config.carrier_writes_enabled is False


def test_shadow_production_refuses_local_fallback():
    with pytest.raises(UnsafeRuntimeConfiguration, match="refuses local fallback"):
        load_runtime_configuration({"SKYSOLVER_RUNTIME_MODE": "shadow-production"})


def test_shadow_accepts_complete_durable_read_only_configuration():
    config = load_runtime_configuration({
        "SKYSOLVER_RUNTIME_MODE": "shadow-production",
        "SKYSOLVER_PERSISTENCE_BACKEND": "aurora-postgresql",
        "SKYSOLVER_EVENT_BACKEND": "amazon-msk",
        "SKYSOLVER_DATABASE_URL": "postgresql://iam@cluster/db",
        "MSK_BOOTSTRAP_SERVERS": "broker:9098",
    })
    assert config.is_production_shaped
    assert config.carrier_writes_enabled is False


def test_api_refuses_local_store_even_when_durable_endpoints_are_configured(monkeypatch):
    values = {
        "SKYSOLVER_RUNTIME_MODE": "shadow-production",
        "SKYSOLVER_PERSISTENCE_BACKEND": "aurora-postgresql",
        "SKYSOLVER_EVENT_BACKEND": "amazon-msk",
        "SKYSOLVER_DATABASE_URL": "postgresql://iam@cluster/db",
        "MSK_BOOTSTRAP_SERVERS": "broker:9098",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(UnsafeRuntimeConfiguration, match="refuses the local demo store"):
        create_app()


def test_carrier_writes_remain_build_time_disabled():
    with pytest.raises(UnsafeRuntimeConfiguration, match="signed release gate"):
        load_runtime_configuration({
            "SKYSOLVER_RUNTIME_MODE": "controlled-production",
            "SKYSOLVER_PERSISTENCE_BACKEND": "aurora-postgresql",
            "SKYSOLVER_EVENT_BACKEND": "amazon-msk",
            "SKYSOLVER_DATABASE_URL": "postgresql://iam@cluster/db",
            "MSK_BOOTSTRAP_SERVERS": "broker:9098",
            "SKYSOLVER_ENABLE_CARRIER_WRITES": "true",
        })
