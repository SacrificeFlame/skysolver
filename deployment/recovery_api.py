"""Stateful synthetic OCC recovery workflow used by the dashboard API.

The store deliberately models production contracts (versions, idempotency,
audit and legal validation) while remaining an explicitly synthetic adapter.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


FLIGHTS = [
    {"id": "SK418", "origin": "ORD", "destination": "DEN", "aircraft": {"registration": "N418SK", "type": "A321", "status": "blocked"}, "gate": "C14", "proposed_gate": "C16", "crew": {"id": "C-184", "status": "illegal", "duty_remaining": "-00:38", "qualifications": ["A321"]}, "passengers": 186, "connections": 42, "delay": 92, "state": "recovery_pending", "tier": "tier1", "risk": "critical"},
    {"id": "SK226", "origin": "ORD", "destination": "BOS", "aircraft": {"registration": "N226SK", "type": "B737", "status": "available"}, "gate": "B08", "proposed_gate": "B08", "crew": {"id": "C-072", "status": "searching", "duty_remaining": "03:42", "qualifications": ["B737"]}, "passengers": 149, "connections": 37, "delay": 74, "state": "solving", "tier": "tier1", "risk": "high"},
    {"id": "SK902", "origin": "ORD", "destination": "LAX", "aircraft": {"registration": "N902SK", "type": "B787", "status": "blocked"}, "gate": "C19", "proposed_gate": "C21", "crew": {"id": "C-811", "status": "illegal", "duty_remaining": "00:12", "qualifications": ["B787", "ETOPS"]}, "passengers": 268, "connections": 61, "delay": 61, "state": "human_review", "tier": "tier3", "risk": "critical"},
    {"id": "SK511", "origin": "DFW", "destination": "ORD", "aircraft": {"registration": "N511SK", "type": "A320", "status": "inbound"}, "gate": "B16", "proposed_gate": "B16", "crew": {"id": "C-333", "status": "legal", "duty_remaining": "04:26", "qualifications": ["A320"]}, "passengers": 172, "connections": 24, "delay": 48, "state": "protected", "tier": "tier1", "risk": "medium"},
    {"id": "SK144", "origin": "ORD", "destination": "ATL", "aircraft": {"registration": "N144SK", "type": "B737", "status": "ready"}, "gate": "B11", "proposed_gate": "B11", "crew": {"id": "C-072", "status": "legal", "duty_remaining": "03:42", "qualifications": ["B737"]}, "passengers": 153, "connections": 18, "delay": 43, "state": "recovered", "tier": "tier1", "risk": "low"},
]

DISRUPTIONS = [{
    "id": "DSP-ORD-0726", "severity": "critical", "title": "ORD departure ground stop",
    "summary": "Thunderstorm cell closed departures until 19:40Z; crew, aircraft and passenger dependencies are cascading across four hubs.",
    "source": "NOAA / airport flow control", "confidence": 0.96, "started_at": "2026-07-31T17:58:00Z",
    "deadline": "2026-07-31T19:40:00Z", "partitions": ["ORD", "DEN", "DFW", "BOS"],
    "affected_flights": [f["id"] for f in FLIGHTS], "illegal_crews": 7, "blocked_aircraft": 4,
    "passengers": 1284, "status": "active",
}]

CANDIDATES = [
    {"id": "PLAN-A", "name": "Network balance", "recommended": True, "legal": True, "coverage": 0.92, "flights_recovered": 11, "total_delay": 486, "max_delay": 92, "illegal_crews": 0, "aircraft_swaps": 2, "gate_conflicts": 0, "misconnections": 126, "passengers_recovered": 942, "cost": 218400, "risk": "low", "warnings": ["2 positioning flights required"], "changes": ["Assign C-184 relief crew to SK418", "Swap SK902 equipment with SK701", "Move SK418 from C14 to C16"]},
    {"id": "PLAN-B", "name": "Passenger priority", "recommended": False, "legal": True, "coverage": 0.83, "flights_recovered": 10, "total_delay": 531, "max_delay": 106, "illegal_crews": 0, "aircraft_swaps": 1, "gate_conflicts": 1, "misconnections": 58, "passengers_recovered": 1081, "cost": 246900, "risk": "medium", "warnings": ["Gate C16 remains constrained", "SK226 holds 14 minutes"], "changes": ["Protect 37 SK226 connections", "Consolidate two DEN rotations", "Cancel SK620"]},
    {"id": "PLAN-C", "name": "Cost containment", "recommended": False, "legal": False, "coverage": 0.75, "flights_recovered": 9, "total_delay": 402, "max_delay": 88, "illegal_crews": 1, "aircraft_swaps": 0, "gate_conflicts": 0, "misconnections": 244, "passengers_recovered": 706, "cost": 171200, "risk": "high", "warnings": ["FAR-117.13 duty limit on crew C-184"], "changes": ["Extend C-184 duty by 38 minutes", "Cancel SK902"]},
]


class WorkflowError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class RecoveryStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._recoveries = {}
        self._audit = []
        self._idempotency = {}

    @staticmethod
    def envelope(status: str, state_version: int, **extra):
        return {"correlation_id": str(uuid.uuid4()), "state_version": state_version, "action_status": status, "rule_violations": [], **extra}

    def disruptions(self):
        return deepcopy(DISRUPTIONS)

    def disruption(self, disruption_id):
        item = next((d for d in DISRUPTIONS if d["id"] == disruption_id), None)
        if not item:
            raise WorkflowError(404, "not_found", "Disruption not found")
        return deepcopy(item)

    def flight(self, flight_id):
        item = next((f for f in FLIGHTS if f["id"] == flight_id), None)
        if not item:
            raise WorkflowError(404, "not_found", "Flight not found")
        return deepcopy(item)

    def create(self, payload):
        with self._lock:
            rid = f"RCV-{uuid.uuid4().hex[:8].upper()}"
            recovery = {"id": rid, "disruption_id": payload.get("disruption_id", DISRUPTIONS[0]["id"]), "partition_id": payload.get("partition_id", "ORD"), "objective": payload.get("objective", "balanced"), "status": "awaiting_review", "stage": "candidate_comparison", "tier": "tier2", "progress": 72, "state_version": 1, "selected_candidate_id": None, "validated": False, "deployed": False, "created_at": _now(), "updated_at": _now(), "candidates": deepcopy(CANDIDATES), "acknowledgements": []}
            self._recoveries[rid] = recovery
            self._record(rid, "recovery_created", "operator", "Tiered solve completed with 3 candidates")
            return self.envelope("awaiting_review", 1, recovery=deepcopy(recovery))

    def get(self, recovery_id):
        if recovery_id not in self._recoveries:
            raise WorkflowError(404, "not_found", "Recovery not found")
        return deepcopy(self._recoveries[recovery_id])

    def candidates(self, recovery_id):
        return self.get(recovery_id)["candidates"]

    def _version(self, recovery, payload):
        expected = payload.get("state_version")
        if expected is None or int(expected) != recovery["state_version"]:
            raise WorkflowError(409, "stale_state", f"Expected version {recovery['state_version']}")

    def decide(self, recovery_id, payload):
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            candidate = next((c for c in recovery["candidates"] if c["id"] == payload.get("candidate_id")), None)
            if not candidate:
                raise WorkflowError(404, "candidate_not_found", "Candidate not found")
            action = payload.get("action", "approve")
            if action == "approve" and not candidate["legal"]:
                raise WorkflowError(422, "illegal_plan", candidate["warnings"][0])
            if action == "override" and not str(payload.get("reason", "")).strip():
                raise WorkflowError(422, "reason_required", "Human override requires a reason")
            recovery.update({"selected_candidate_id": candidate["id"] if action != "reject" else None, "status": "validating" if action != "reject" else "awaiting_review", "stage": "rule_validation" if action != "reject" else "candidate_comparison", "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, f"candidate_{action}", payload.get("operator_id", "ops-controller"), payload.get("reason") or candidate["name"])
            return self.envelope(recovery["status"], recovery["state_version"], recovery=deepcopy(recovery))

    def validate(self, recovery_id, payload):
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["selected_candidate_id"]:
                raise WorkflowError(422, "candidate_required", "Select a candidate before validation")
            candidate = next(c for c in recovery["candidates"] if c["id"] == recovery["selected_candidate_id"])
            if not candidate["legal"]:
                raise WorkflowError(422, "illegal_plan", candidate["warnings"][0])
            recovery.update({"validated": True, "status": "ready_to_deploy", "stage": "validated", "progress": 90, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "rules_validated", payload.get("operator_id", "ops-controller"), "144 hard constraints passed")
            return self.envelope("ready_to_deploy", recovery["state_version"], recovery=deepcopy(recovery))

    def deploy(self, recovery_id, payload, idempotency_key):
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency:
                return deepcopy(self._idempotency[idempotency_key])
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["validated"]:
                raise WorkflowError(422, "validation_required", "Plan must pass independent validation")
            acknowledgements = [{"resource": "crew", "status": "acknowledged"}, {"resource": "aircraft", "status": "acknowledged"}, {"resource": "gates", "status": "acknowledged"}, {"resource": "passengers", "status": "acknowledged"}]
            recovery.update({"deployed": True, "status": "deployed", "stage": "recovered", "progress": 100, "acknowledgements": acknowledgements, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "plan_deployed", payload.get("operator_id", "ops-controller"), recovery["selected_candidate_id"])
            result = self.envelope("deployed", recovery["state_version"], recovery=deepcopy(recovery), acknowledgements=acknowledgements)
            if idempotency_key:
                self._idempotency[idempotency_key] = deepcopy(result)
            return result

    def rollback(self, recovery_id, payload):
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["deployed"]:
                raise WorkflowError(422, "not_deployed", "Only deployed plans can be rolled back")
            recovery.update({"deployed": False, "validated": False, "status": "awaiting_review", "stage": "candidate_comparison", "progress": 72, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "deployment_rolled_back", payload.get("operator_id", "ops-controller"), payload.get("reason", "Operator rollback"))
            return self.envelope("rolled_back", recovery["state_version"], recovery=deepcopy(recovery))

    def audit(self):
        return deepcopy(list(reversed(self._audit)))

    def events(self):
        return deepcopy(self._audit[-50:])

    def _record(self, recovery_id, action, operator, detail):
        self._audit.append({"id": str(uuid.uuid4()), "recovery_id": recovery_id, "action": action, "operator": operator, "detail": detail, "timestamp": _now(), "ruleset_version": "synthetic-far117-v2"})


recovery_store = RecoveryStore()
