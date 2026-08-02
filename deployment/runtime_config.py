"""Fail-closed runtime configuration for operational authority.

The synthetic process is allowed to use local persistence. Any environment
claiming to be shadow or controlled production must use the durable service
composition; falling back to JSON is a startup error, never a warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os


class RuntimeMode(str, Enum):
    DEVELOPMENT = "development"
    INTEGRATION = "integration"
    AIRLINE_SANDBOX = "airline-sandbox"
    SHADOW_PRODUCTION = "shadow-production"
    CONTROLLED_PRODUCTION = "controlled-production"


class UnsafeRuntimeConfiguration(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeConfiguration:
    mode: RuntimeMode
    persistence_backend: str
    event_backend: str
    carrier_writes_enabled: bool
    database_url_present: bool
    msk_bootstrap_present: bool

    @property
    def is_production_shaped(self) -> bool:
        return self.mode in {RuntimeMode.SHADOW_PRODUCTION, RuntimeMode.CONTROLLED_PRODUCTION}


def load_runtime_configuration(environment: dict[str, str] | None = None) -> RuntimeConfiguration:
    values = environment if environment is not None else os.environ
    try:
        mode = RuntimeMode(values.get("SKYSOLVER_RUNTIME_MODE", "development"))
    except ValueError as exc:
        raise UnsafeRuntimeConfiguration("SKYSOLVER_RUNTIME_MODE is not recognized") from exc
    configuration = RuntimeConfiguration(
        mode=mode,
        persistence_backend=values.get("SKYSOLVER_PERSISTENCE_BACKEND", "local-json"),
        event_backend=values.get("SKYSOLVER_EVENT_BACKEND", "process-local"),
        carrier_writes_enabled=values.get("SKYSOLVER_ENABLE_CARRIER_WRITES", "false").lower() == "true",
        database_url_present=bool(values.get("SKYSOLVER_DATABASE_URL")),
        msk_bootstrap_present=bool(values.get("MSK_BOOTSTRAP_SERVERS")),
    )
    _validate(configuration)
    return configuration


def _validate(configuration: RuntimeConfiguration) -> None:
    if configuration.is_production_shaped:
        missing = []
        if configuration.persistence_backend != "aurora-postgresql":
            missing.append("SKYSOLVER_PERSISTENCE_BACKEND=aurora-postgresql")
        if configuration.event_backend != "amazon-msk":
            missing.append("SKYSOLVER_EVENT_BACKEND=amazon-msk")
        if not configuration.database_url_present:
            missing.append("SKYSOLVER_DATABASE_URL")
        if not configuration.msk_bootstrap_present:
            missing.append("MSK_BOOTSTRAP_SERVERS")
        if missing:
            raise UnsafeRuntimeConfiguration(
                "Production-shaped mode refuses local fallback; missing: " + ", ".join(missing)
            )
    if configuration.mode is not RuntimeMode.CONTROLLED_PRODUCTION and configuration.carrier_writes_enabled:
        raise UnsafeRuntimeConfiguration("Carrier writes are permitted only in controlled-production mode")
    if configuration.mode is RuntimeMode.CONTROLLED_PRODUCTION and configuration.carrier_writes_enabled:
        raise UnsafeRuntimeConfiguration(
            "Carrier writes require the external signed release gate; this build keeps them disabled"
        )
