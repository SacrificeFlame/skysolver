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
    {"id": "AI421", "origin": "DEL", "destination": "BOM", "aircraft": {"registration": "VT-EXA", "type": "A321", "status": "blocked"}, "gate": "T3-42", "proposed_gate": "T3-46", "crew": {"id": "IC-184", "status": "illegal", "duty_remaining": "-00:38", "qualifications": ["A321"]}, "passengers": 186, "connections": 42, "delay": 92, "state": "recovery_pending", "tier": "tier1", "risk": "critical"},
    {"id": "6E203", "origin": "BLR", "destination": "DEL", "aircraft": {"registration": "VT-IAB", "type": "A320neo", "status": "available"}, "gate": "D08", "proposed_gate": "D08", "crew": {"id": "IC-072", "status": "searching", "duty_remaining": "03:42", "qualifications": ["A320"]}, "passengers": 179, "connections": 37, "delay": 74, "state": "solving", "tier": "tier1", "risk": "high"},
    {"id": "UK945", "origin": "DEL", "destination": "HYD", "aircraft": {"registration": "VT-TNE", "type": "A321neo", "status": "blocked"}, "gate": "T3-31", "proposed_gate": "T3-35", "crew": {"id": "IC-811", "status": "illegal", "duty_remaining": "00:12", "qualifications": ["A321"]}, "passengers": 168, "connections": 31, "delay": 61, "state": "human_review", "tier": "tier3", "risk": "critical"},
    {"id": "AI807", "origin": "BOM", "destination": "DEL", "aircraft": {"registration": "VT-ANR", "type": "B787-8", "status": "inbound"}, "gate": "T2-16", "proposed_gate": "T2-16", "crew": {"id": "IC-333", "status": "legal", "duty_remaining": "04:26", "qualifications": ["B787"]}, "passengers": 242, "connections": 54, "delay": 48, "state": "protected", "tier": "tier1", "risk": "medium"},
    {"id": "6E531", "origin": "DEL", "destination": "CCU", "aircraft": {"registration": "VT-IZR", "type": "A320neo", "status": "ready"}, "gate": "T2-11", "proposed_gate": "T2-11", "crew": {"id": "IC-590", "status": "legal", "duty_remaining": "03:42", "qualifications": ["A320"]}, "passengers": 183, "connections": 18, "delay": 43, "state": "recovered", "tier": "tier1", "risk": "low"},
]

DISRUPTIONS = [{
    "id": "DSP-DEL-0726", "severity": "critical", "title": "Delhi low-visibility departure restrictions",
    "summary": "Dense fog reduced DEL departure capacity; crew, aircraft and passenger dependencies are cascading across four Indian network partitions.",
    "source": "IMD / Delhi ATC flow control", "confidence": 0.96, "started_at": "2026-07-31T00:28:00Z",
    "deadline": "2026-07-31T02:10:00Z", "partitions": ["DEL", "BOM", "BLR", "HYD"],
    "affected_flights": [f["id"] for f in FLIGHTS], "illegal_crews": 7, "blocked_aircraft": 4,
    "passengers": 1284, "status": "active",
}]

CANDIDATES = [
    {"id": "PLAN-A", "name": "Network balance", "recommended": True, "legal": True, "coverage": 0.92, "flights_recovered": 11, "total_delay": 486, "max_delay": 92, "illegal_crews": 0, "aircraft_swaps": 2, "gate_conflicts": 0, "misconnections": 126, "passengers_recovered": 942, "cost": 18100000, "risk": "low", "warnings": ["2 positioning flights required"], "changes": ["Assign IC-927 relief crew to AI421", "Swap UK945 equipment with AI701", "Move AI421 from T3-42 to T3-46"]},
    {"id": "PLAN-B", "name": "Passenger priority", "recommended": False, "legal": True, "coverage": 0.83, "flights_recovered": 10, "total_delay": 531, "max_delay": 106, "illegal_crews": 0, "aircraft_swaps": 1, "gate_conflicts": 1, "misconnections": 58, "passengers_recovered": 1081, "cost": 20500000, "risk": "medium", "warnings": ["Gate T3-46 remains constrained", "6E203 holds 14 minutes"], "changes": ["Protect 37 6E203 connections", "Consolidate two BOM rotations", "Cancel AI620"]},
    {"id": "PLAN-C", "name": "Cost containment", "recommended": False, "legal": False, "coverage": 0.75, "flights_recovered": 9, "total_delay": 402, "max_delay": 88, "illegal_crews": 1, "aircraft_swaps": 0, "gate_conflicts": 0, "misconnections": 244, "passengers_recovered": 706, "cost": 14200000, "risk": "high", "warnings": ["DGCA FDTL duty limit on crew IC-184"], "changes": ["Extend IC-184 duty by 38 minutes", "Cancel UK945"]},
]

AIRPORTS = {
    "DEL": {"name": "Delhi", "x": 445, "y": 112}, "BOM": {"name": "Mumbai", "x": 332, "y": 262},
    "BLR": {"name": "Bengaluru", "x": 409, "y": 361}, "HYD": {"name": "Hyderabad", "x": 432, "y": 292},
    "CCU": {"name": "Kolkata", "x": 614, "y": 230}, "MAA": {"name": "Chennai", "x": 472, "y": 377},
    "AMD": {"name": "Ahmedabad", "x": 330, "y": 194}, "GOI": {"name": "Goa", "x": 342, "y": 318},
}

ROUTES = {
    "AI421": {"distance_km": 1138, "block_minutes": 135, "scheduled": ["08:10", "10:15"], "proposed": ["08:37", "10:52"], "airspace": "Delhi LVP active below CAT III minima"},
    "6E203": {"distance_km": 1709, "block_minutes": 170, "scheduled": ["08:28", "11:18"], "proposed": ["08:49", "11:39"], "airspace": "Northbound arrival sequencing at DEL"},
    "UK945": {"distance_km": 1266, "block_minutes": 145, "scheduled": ["08:42", "11:07"], "proposed": ["09:03", "11:28"], "airspace": "DEL departure metering"},
    "AI807": {"distance_km": 1138, "block_minutes": 135, "scheduled": ["08:57", "11:12"], "proposed": ["09:10", "11:25"], "airspace": "DEL arrival holding risk"},
    "6E531": {"distance_km": 1305, "block_minutes": 140, "scheduled": ["09:15", "11:35"], "proposed": ["09:28", "11:48"], "airspace": "Normal routing"},
}


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

    def routes(self):
        return [self.route(flight["id"]) for flight in FLIGHTS]

    def route(self, flight_id):
        flight = next((f for f in FLIGHTS if f["id"] == flight_id), None)
        if not flight or flight_id not in ROUTES:
            raise WorkflowError(404, "route_not_found", "Planned route not found")
        meta = ROUTES[flight_id]
        origin, destination = AIRPORTS[flight["origin"]], AIRPORTS[flight["destination"]]
        return deepcopy({
            "flight_id": flight_id, "origin": {"code": flight["origin"], **origin},
            "destination": {"code": flight["destination"], **destination},
            "aircraft": flight["aircraft"], "crew_id": flight["crew"]["id"],
            "distance_km": meta["distance_km"], "block_minutes": meta["block_minutes"],
            "scheduled": {"departure": meta["scheduled"][0], "arrival": meta["scheduled"][1]},
            "proposed": {"departure": meta["proposed"][0], "arrival": meta["proposed"][1]},
            "restriction": meta["airspace"], "legal": flight["crew"]["status"] != "illegal",
            "movement_segments": [
                {"time": meta["proposed"][0], "place": flight["origin"], "kind": "report", "detail": f"Gate {flight['proposed_gate']}"},
                {"time": meta["proposed"][0], "place": flight_id, "kind": "operate", "detail": f"{flight['origin']} to {flight['destination']}"},
                {"time": meta["proposed"][1], "place": flight["destination"], "kind": "release", "detail": "Duty segment complete"},
            ],
        })

    def create(self, payload):
        with self._lock:
            rid = f"RCV-{uuid.uuid4().hex[:8].upper()}"
            recovery = {"id": rid, "disruption_id": payload.get("disruption_id", DISRUPTIONS[0]["id"]), "partition_id": payload.get("partition_id", "DEL"), "objective": payload.get("objective", "balanced"), "status": "awaiting_review", "stage": "candidate_comparison", "tier": "tier2", "progress": 72, "state_version": 1, "selected_candidate_id": None, "validated": False, "deployed": False, "created_at": _now(), "updated_at": _now(), "candidates": deepcopy(CANDIDATES), "acknowledgements": []}
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
