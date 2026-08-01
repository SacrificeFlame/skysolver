"""Fail-closed dependency registry for shadow and production compositions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import time
from typing import Callable


REQUIRED_PRODUCTION_DEPENDENCIES = frozenset({
    "aurora", "msk", "validation_service", "artifact_store", "required_adapters",
})


class IncompleteProductionComposition(RuntimeError): pass


@dataclass(frozen=True)
class DependencyResult:
    name: str
    ready: bool
    authoritative: bool
    checked_at: str
    latency_ms: float
    code: str
    detail: str


@dataclass(frozen=True)
class DependencyProbe:
    name: str
    check: Callable[[], bool]
    authoritative: bool = True


class RuntimeDependencyRegistry:
    def __init__(self, probes: list[DependencyProbe],
                 required: frozenset[str] = REQUIRED_PRODUCTION_DEPENDENCIES):
        self.probes = {probe.name: probe for probe in probes}
        self.required = required

    def assert_configured(self) -> None:
        missing = sorted(self.required - self.probes.keys())
        non_authoritative = sorted(name for name in self.required
                                   if name in self.probes and not self.probes[name].authoritative)
        if missing or non_authoritative:
            parts=[]
            if missing: parts.append("missing probes: " + ", ".join(missing))
            if non_authoritative: parts.append("non-authoritative probes: " + ", ".join(non_authoritative))
            raise IncompleteProductionComposition("; ".join(parts))

    def snapshot(self) -> dict:
        results=[]
        for name in sorted(self.probes):
            probe=self.probes[name];started=time.perf_counter()
            try:
                ready=bool(probe.check());code="ready" if ready else "dependency_not_ready"
                detail="Dependency acknowledged readiness" if ready else "Dependency returned a non-ready result"
            except Exception as exc:
                ready=False;code="dependency_probe_failed";detail=type(exc).__name__
            results.append(DependencyResult(name,ready,probe.authoritative,
                datetime.now(timezone.utc).isoformat(),round((time.perf_counter()-started)*1000,3),code,detail))
        required_results=[item for item in results if item.name in self.required]
        ready=(len(required_results)==len(self.required)
               and all(item.ready and item.authoritative for item in required_results))
        return {"ready":ready,"authoritative":True,"dependencies":[asdict(item) for item in results],
                "required":sorted(self.required),"checked_at":datetime.now(timezone.utc).isoformat()}


def aurora_probe(connection_factory) -> Callable[[], bool]:
    def check() -> bool:
        connection=connection_factory()
        try:
            cursor=connection.cursor();cursor.execute("SELECT 1");row=cursor.fetchone()
            connection.commit();return bool(row and int(row[0])==1)
        except Exception:
            connection.rollback();raise
        finally:connection.close()
    return check


def callable_probe(function: Callable[[], object]) -> Callable[[], bool]:
    """Adapt clients whose health method returns bool or a ready/status mapping."""
    def check() -> bool:
        result=function()
        if isinstance(result,bool):return result
        if isinstance(result,dict):return bool(result.get("ready") or result.get("status") in {"ready","healthy"})
        return False
    return check
