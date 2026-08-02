"""Freshness, reconciliation and data-quality deployment interlock."""

from __future__ import annotations

from dataclasses import asdict,dataclass
from datetime import datetime,timezone
import threading


@dataclass(frozen=True)
class SourceHealth:
    source_system:str
    authoritative:bool
    required_for_solve:bool
    required_for_deployment:bool
    last_source_timestamp:datetime|None
    last_ingested_at:datetime|None
    max_freshness_seconds:int
    dead_letter_count:int=0
    reconciliation_drift_count:int=0
    circuit_state:str="closed"
    contract_version:str="unknown"

    def evaluate(self,now:datetime)->dict:
        age=None if self.last_ingested_at is None else max(0,(now-self.last_ingested_at).total_seconds())
        findings=[]
        if not self.authoritative: findings.append({"code":"SOURCE_NOT_AUTHORITATIVE","severity":"blocking","message":f"{self.source_system} is not authoritative"})
        if age is None or age>self.max_freshness_seconds: findings.append({"code":"SOURCE_STALE","severity":"blocking","message":f"{self.source_system} exceeds its freshness SLA"})
        if self.dead_letter_count: findings.append({"code":"DEAD_LETTERS_PENDING","severity":"blocking","message":f"{self.dead_letter_count} source records require resolution"})
        if self.reconciliation_drift_count: findings.append({"code":"RECONCILIATION_DRIFT","severity":"blocking","message":f"{self.reconciliation_drift_count} records differ from the source"})
        if self.circuit_state!="closed": findings.append({"code":"ADAPTER_CIRCUIT_OPEN","severity":"blocking","message":f"Adapter circuit is {self.circuit_state}"})
        return {**asdict(self),"last_source_timestamp":self.last_source_timestamp.isoformat() if self.last_source_timestamp else None,
                "last_ingested_at":self.last_ingested_at.isoformat() if self.last_ingested_at else None,"age_seconds":age,
                "fresh":age is not None and age<=self.max_freshness_seconds,"findings":findings}


class DataHealthRegistry:
    def __init__(self,allow_synthetic_solve=False):self._sources={};self._lock=threading.RLock();self.allow_synthetic_solve=allow_synthetic_solve
    def update(self,source:SourceHealth):
        with self._lock:self._sources[source.source_system]=source
    def snapshot(self,now=None):
        now=now or datetime.now(timezone.utc)
        with self._lock:evaluated=[source.evaluate(now) for source in self._sources.values()]
        findings=[finding for source in evaluated for finding in source["findings"]]
        solve_blocked=any(source["findings"] and source["required_for_solve"] for source in evaluated)
        deployment_blocked=any(source["findings"] and source["required_for_deployment"] for source in evaluated) or not evaluated
        return {"status":"healthy" if not findings else "blocked_for_operations","solve_allowed":self.allow_synthetic_solve or not solve_blocked,
                "deployment_allowed":not deployment_blocked,"sources":evaluated,"findings":findings,"evaluated_at":now.isoformat()}


def demo_registry():
    registry=DataHealthRegistry(allow_synthetic_solve=True)
    registry.update(SourceHealth("skysolver-scenario-fixture",False,True,True,None,None,0,contract_version="fixture-v1"))
    return registry
