"""Stateful synthetic OCC recovery workflow used by the dashboard API.

The store deliberately models production contracts (versions, idempotency,
audit and legal validation) while remaining an explicitly synthetic adapter.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
import threading
import uuid

from rules.engine import Assignment, CrewMember, FlightLeg, Qualification, RulesEngine
from solvers.tier1 import solve_partition as solve_tier1
from solvers.tier2 import solve_partition_detailed as solve_tier2_detailed
from deployment.command_state import CommandStatus, DeploymentConflict, DeploymentRegistry, DeploymentStatus
from core.resource_holds import HoldConflict, ResourceHoldRegistry
from rules.certificates import CertificateIssuer, LegalityCertificate
from solvers.tier3_api import SuggestionStatus, generate_suggestions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


FLIGHTS = [
    {"id": "AI421", "origin": "DEL", "destination": "BOM", "aircraft": {"registration": "VT-EXA", "type": "A321", "status": "blocked"}, "gate": "T3-42", "proposed_gate": "T3-46", "crew": {"id": "IC-184", "status": "illegal", "duty_remaining": "-00:38", "qualifications": ["A321"]}, "passengers": 186, "connections": 42, "delay": 92, "state": "recovery_pending", "tier": "tier1", "risk": "critical"},
    {"id": "6E203", "origin": "BLR", "destination": "DEL", "aircraft": {"registration": "VT-IAB", "type": "A320neo", "status": "available"}, "gate": "D08", "proposed_gate": "D08", "crew": {"id": "IC-072", "status": "searching", "duty_remaining": "03:42", "qualifications": ["A320"]}, "passengers": 179, "connections": 37, "delay": 74, "state": "solving", "tier": "tier1", "risk": "high"},
    {"id": "UK945", "origin": "DEL", "destination": "HYD", "aircraft": {"registration": "VT-TNE", "type": "A321neo", "status": "blocked"}, "gate": "T3-31", "proposed_gate": "T3-35", "crew": {"id": "IC-811", "status": "illegal", "duty_remaining": "00:12", "qualifications": ["A321"]}, "passengers": 168, "connections": 31, "delay": 61, "state": "human_review", "tier": "tier3", "risk": "critical"},
    {"id": "AI807", "origin": "BOM", "destination": "DEL", "aircraft": {"registration": "VT-ANR", "type": "B787-8", "status": "inbound"}, "gate": "T2-16", "proposed_gate": "T2-16", "crew": {"id": "IC-333", "status": "illegal", "duty_remaining": "-00:15", "qualifications": ["B787"]}, "passengers": 242, "connections": 54, "delay": 48, "state": "human_review", "tier": "tier3", "risk": "critical"},
    {"id": "6E531", "origin": "DEL", "destination": "CCU", "aircraft": {"registration": "VT-IZR", "type": "A320neo", "status": "ready"}, "gate": "T2-11", "proposed_gate": "T2-11", "crew": {"id": "IC-590", "status": "legal", "duty_remaining": "03:42", "qualifications": ["A320"]}, "passengers": 183, "connections": 18, "delay": 43, "state": "recovered", "tier": "tier1", "risk": "low"},
]

DISRUPTIONS = [{
    "id": "DSP-DEL-0726", "severity": "critical", "title": "Delhi low-visibility departure restrictions",
    "summary": "Dense fog reduced DEL departure capacity; crew, aircraft and passenger dependencies are cascading across four Indian network partitions.",
    "source": "IMD / Delhi ATC flow control", "confidence": 0.96, "started_at": "2026-07-31T00:28:00Z",
    "deadline": "2026-07-31T02:10:00Z", "partitions": ["DEL", "BOM", "BLR", "HYD"],
    "affected_flights": [f["id"] for f in FLIGHTS], "illegal_crews": 3, "blocked_aircraft": 2,
    "passengers": 1284, "status": "active",
}]

DATA_PROVENANCE = {
    "mode": "synthetic-demo",
    "authoritative": False,
    "source_system": "skysolver-scenario-fixture",
    "state_version": 1,
    "freshness": "fixture",
    "warning": "SYNTHETIC DEMO — NOT FOR OPERATIONAL USE",
}

# Authoritative within the demo fixture: route validation must use these
# profiles rather than manufacturing an appropriately rested crew member.
CREW_PROFILES = {
    "IC-184": {"location": "DEL", "qualifications": ["A321"], "rest_hours": 5},
    "IC-072": {"location": "BLR", "qualifications": ["A320"], "rest_hours": 12},
    "IC-811": {"location": "DEL", "qualifications": ["A320"], "rest_hours": 12},
    "IC-333": {"location": "BOM", "qualifications": ["B787"], "rest_hours": 12},
    "IC-590": {"location": "DEL", "qualifications": ["A320"], "rest_hours": 12},
}

# Full crew roster: on-duty crew plus standby/reserve replacements. Qualifications,
# base and rest hours are real inputs to the FAR117/DGCA-style legality engine, so a
# reassignment preview returns a genuine legal/illegal verdict — nothing is faked.
CREW_ROSTER = [
    # On-duty incumbents (three are illegal and drive the open recovery cases).
    {"id": "IC-184", "name": "Rohit Sharma", "rank": "Captain", "base": "DEL", "qualifications": ["A321"], "status": "illegal", "duty_remaining": "-00:38", "rest_hours": 5, "assigned_flight": "AI421", "seniority": 8},
    {"id": "IC-811", "name": "Vikram Singh", "rank": "Captain", "base": "DEL", "qualifications": ["A321"], "status": "illegal", "duty_remaining": "00:12", "rest_hours": 6, "assigned_flight": "UK945", "seniority": 6},
    {"id": "IC-333", "name": "Meera Nair", "rank": "Captain", "base": "BOM", "qualifications": ["B787"], "status": "illegal", "duty_remaining": "-00:15", "rest_hours": 5, "assigned_flight": "AI807", "seniority": 14},
    {"id": "IC-072", "name": "Ananya Rao", "rank": "Captain", "base": "BLR", "qualifications": ["A320"], "status": "on_duty", "duty_remaining": "03:42", "rest_hours": 12, "assigned_flight": "6E203", "seniority": 11},
    {"id": "IC-590", "name": "Arjun Menon", "rank": "Captain", "base": "DEL", "qualifications": ["A320"], "status": "on_duty", "duty_remaining": "03:42", "rest_hours": 12, "assigned_flight": "6E531", "seniority": 9},
    # Standby / reserve pool available for reassignment.
    {"id": "IC-205", "name": "Kabir Khan", "rank": "Captain", "base": "DEL", "qualifications": ["A321", "A320"], "status": "standby", "duty_remaining": "09:00", "rest_hours": 13, "assigned_flight": None, "seniority": 12},
    {"id": "IC-318", "name": "Priya Iyer", "rank": "Captain", "base": "DEL", "qualifications": ["A321", "A320"], "status": "standby", "duty_remaining": "10:30", "rest_hours": 14, "assigned_flight": None, "seniority": 15},
    {"id": "IC-401", "name": "Aditya Verma", "rank": "Captain", "base": "DEL", "qualifications": ["A321"], "status": "standby", "duty_remaining": "08:15", "rest_hours": 11, "assigned_flight": None, "seniority": 10},
    {"id": "IC-419", "name": "Sneha Joshi", "rank": "First Officer", "base": "DEL", "qualifications": ["A321", "A320"], "status": "standby", "duty_remaining": "09:45", "rest_hours": 12, "assigned_flight": None, "seniority": 7},
    {"id": "IC-533", "name": "Rahul Bose", "rank": "Captain", "base": "DEL", "qualifications": ["A321"], "status": "reserve", "duty_remaining": "07:00", "rest_hours": 10, "assigned_flight": None, "seniority": 9},
    {"id": "IC-612", "name": "Manish Gupta", "rank": "Captain", "base": "DEL", "qualifications": ["A320", "A321"], "status": "standby", "duty_remaining": "08:30", "rest_hours": 11, "assigned_flight": None, "seniority": 8},
    {"id": "IC-688", "name": "Vivek Nair", "rank": "Captain", "base": "DEL", "qualifications": ["A321"], "status": "standby", "duty_remaining": "09:10", "rest_hours": 12, "assigned_flight": None, "seniority": 13},
    {"id": "IC-701", "name": "Imran Sheikh", "rank": "Captain", "base": "DEL", "qualifications": ["A320"], "status": "standby", "duty_remaining": "08:00", "rest_hours": 12, "assigned_flight": None, "seniority": 6},
    {"id": "IC-655", "name": "Ritu Sharma", "rank": "First Officer", "base": "DEL", "qualifications": ["A320"], "status": "reserve", "duty_remaining": "07:20", "rest_hours": 13, "assigned_flight": None, "seniority": 5},
    {"id": "IC-442", "name": "Sana Ali", "rank": "First Officer", "base": "BLR", "qualifications": ["A320"], "status": "standby", "duty_remaining": "09:00", "rest_hours": 12, "assigned_flight": None, "seniority": 5},
    {"id": "IC-663", "name": "Neha Gupta", "rank": "First Officer", "base": "DEL", "qualifications": ["A321"], "status": "reserve", "duty_remaining": "07:30", "rest_hours": 9, "assigned_flight": None, "seniority": 4},
    # B787 pool — deliberately thin: no legal option for AI807, so it must escalate to Tier 3.
    {"id": "IC-507", "name": "Dev Patel", "rank": "Captain", "base": "BOM", "qualifications": ["B787", "A321"], "status": "reserve", "duty_remaining": "07:40", "rest_hours": 9, "assigned_flight": None, "seniority": 13},
    {"id": "IC-560", "name": "Farah Naaz", "rank": "Captain", "base": "DEL", "qualifications": ["B787"], "status": "standby", "duty_remaining": "09:30", "rest_hours": 12, "assigned_flight": None, "seniority": 12},
]

# Fleet: aircraft currently operating the disrupted flights plus available spares.
FLEET = [
    {"registration": "VT-EXA", "type": "A321", "status": "blocked", "location": "DEL", "gate": "T3-42", "assigned_flight": "AI421", "next_available": "On stand — LVP hold"},
    {"registration": "VT-TNE", "type": "A321neo", "status": "blocked", "location": "DEL", "gate": "T3-31", "assigned_flight": "UK945", "next_available": "On stand — LVP hold"},
    {"registration": "VT-IAB", "type": "A320neo", "status": "available", "location": "BLR", "gate": "D08", "assigned_flight": "6E203", "next_available": "Ready"},
    {"registration": "VT-ANR", "type": "B787-8", "status": "inbound", "location": "BOM", "gate": "T2-16", "assigned_flight": "AI807", "next_available": "ETA 09:40"},
    {"registration": "VT-IZR", "type": "A320neo", "status": "ready", "location": "DEL", "gate": "T2-11", "assigned_flight": "6E531", "next_available": "Ready"},
    {"registration": "VT-EXB", "type": "A321", "status": "available", "location": "DEL", "gate": "T3-50", "assigned_flight": None, "next_available": "Spare — ready"},
    {"registration": "VT-ISP", "type": "A320neo", "status": "maintenance", "location": "DEL", "gate": "MRO-2", "assigned_flight": None, "next_available": "AOG — check A2 ETA 14:00"},
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
    durable_authoritative = False

    def __init__(self, state_path=None, carrier_writes_enabled=False):
        self._lock = threading.RLock()
        self._recoveries = {}
        self._audit = []
        self._idempotency = {}
        self._state_path = state_path
        self._carrier_writes_enabled = carrier_writes_enabled
        self._deployment_registry = DeploymentRegistry()
        self._hold_registry = ResourceHoldRegistry()
        self._certificate_issuer = CertificateIssuer("demo-local-key", os.environ.get("SKYSOLVER_DEMO_CERTIFICATE_KEY", "synthetic-demo-not-production").encode(), "validation-demo-process", "2026.08", "demo_in_process_not_certified")
        self._load()

    def _load(self):
        if not self._state_path or not os.path.exists(self._state_path): return
        try:
            with open(self._state_path, "r", encoding="utf-8") as handle: state=json.load(handle)
            self._recoveries=state.get("recoveries",{}); self._audit=state.get("audit",[]); self._idempotency=state.get("idempotency",{})
        except (OSError, ValueError):
            self._recoveries={}; self._audit=[]; self._idempotency={}

    def _persist(self):
        if not self._state_path:return
        temp=f"{self._state_path}.tmp"
        with open(temp,"w",encoding="utf-8") as handle: json.dump({"recoveries":self._recoveries,"audit":self._audit,"idempotency":self._idempotency},handle,indent=2)
        os.replace(temp,self._state_path)

    @staticmethod
    def envelope(status: str, state_version: int, correlation_id=None, causation_id=None, **extra):
        return {"correlation_id": correlation_id or str(uuid.uuid4()), "causation_id": causation_id, "state_version": state_version, "action_status": status, "rule_violations": [], **extra}

    def disruptions(self):
        return [{**deepcopy(item), "provenance": deepcopy(DATA_PROVENANCE)} for item in DISRUPTIONS]

    def disruption(self, disruption_id):
        item = next((d for d in DISRUPTIONS if d["id"] == disruption_id), None)
        if not item:
            raise WorkflowError(404, "not_found", "Disruption not found")
        return {**deepcopy(item), "provenance": deepcopy(DATA_PROVENANCE)}

    def flight(self, flight_id):
        item = next((f for f in FLIGHTS if f["id"] == flight_id), None)
        if not item:
            raise WorkflowError(404, "not_found", "Flight not found")
        return {**deepcopy(item), "provenance": deepcopy(DATA_PROVENANCE)}

    def routes(self):
        return [self.route(flight["id"]) for flight in FLIGHTS]

    def route(self, flight_id):
        flight = next((f for f in FLIGHTS if f["id"] == flight_id), None)
        if not flight or flight_id not in ROUTES:
            raise WorkflowError(404, "route_not_found", "Planned route not found")
        meta = ROUTES[flight_id]
        origin, destination = AIRPORTS[flight["origin"]], AIRPORTS[flight["destination"]]
        return deepcopy({
            "flight_id": flight_id, "origin": {"code": flight["origin"], "o": origin["x"], **origin},
            "destination": {"code": flight["destination"], **destination},
            "aircraft": flight["aircraft"], "crew_id": flight["crew"]["id"],
            "distance_km": meta["distance_km"], "block_minutes": meta["block_minutes"],
            "scheduled": {"departure": meta["scheduled"][0], "arrival": meta["scheduled"][1]},
            "proposed": {"departure": meta["proposed"][0], "arrival": meta["proposed"][1]},
            "restriction": meta["airspace"], "legal": flight["crew"]["status"] != "illegal",
            "provenance": deepcopy(DATA_PROVENANCE),
            "movement_segments": [
                {"time": meta["proposed"][0], "place": flight["origin"], "kind": "report", "detail": f"Gate {flight['proposed_gate']}"},
                {"time": meta["proposed"][0], "place": flight_id, "kind": "operate", "detail": f"{flight['origin']} to {flight['destination']}"},
                {"time": meta["proposed"][1], "place": flight["destination"], "kind": "release", "detail": "Duty segment complete"},
            ],
        })

    def validate_route(self, flight_id, payload=None):
        route=self.route(flight_id); flight=self.flight(flight_id); meta=ROUTES[flight_id]
        day=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
        dep_h,dep_m=map(int,meta["proposed"][0].split(":")); arr_h,arr_m=map(int,meta["proposed"][1].split(":"))
        dep=day+timedelta(hours=dep_h,minutes=dep_m); arr=day+timedelta(hours=arr_h,minutes=arr_m)
        if arr<=dep:arr+=timedelta(days=1)
        aircraft=flight["aircraft"]["type"].replace("-8","").replace("neo","")
        profile=CREW_PROFILES[flight["crew"]["id"]]
        qualifications={Qualification.__members__[name] for name in profile["qualifications"] if name in Qualification.__members__}
        crew=CrewMember(flight["crew"]["id"],flight["origin"],qualifications,current_location=profile["location"],last_rest_end=dep-timedelta(hours=profile["rest_hours"]))
        leg=FlightLeg(flight_id,flight["origin"],flight["destination"],dep,arr,aircraft)
        assignment=Assignment(crew.crew_id,[leg],dep-timedelta(minutes=45),arr+timedelta(minutes=20))
        violations=RulesEngine.validate_assignment(crew,assignment)
        result=self.envelope("valid" if not violations else "invalid",DATA_PROVENANCE["state_version"],correlation_id=(payload or {}).get("correlation_id"),causation_id=(payload or {}).get("causation_id"),flight_id=flight_id,legal=not violations,ruleset_version=RulesEngine.RULESET_VERSION,provenance=deepcopy(DATA_PROVENANCE),checks={"airport_sequence":route["origin"]["code"]==leg.origin and route["destination"]["code"]==leg.destination,"positive_distance":route["distance_km"]>0,"arrival_after_departure":arr>dep},rule_violations=[v.to_dict() for v in violations])
        self._record(flight_id,"route_validated",(payload or {}).get("operator_id","ops-controller"),f"{len(violations)} legality findings")
        self._persist(); return result

    def crew_roster(self):
        on_flight={f["id"]:f for f in FLIGHTS}
        items=[]
        for c in CREW_ROSTER:
            item=deepcopy(c)
            fl=on_flight.get(c["assigned_flight"] or "")
            if fl:
                item["current_route"]=f'{fl["origin"]} → {fl["destination"]}'
                item["current_origin"]=fl["origin"]; item["current_destination"]=fl["destination"]
                item["current_aircraft"]=fl["aircraft"]["type"]; item["current_gate"]=fl["gate"]
                item["passengers"]=fl["passengers"]
            else:
                item["current_route"]=None
            items.append(item)
        return {"items":items,"provenance":deepcopy(DATA_PROVENANCE)}

    def aircraft_fleet(self):
        return {"items":[deepcopy(a) for a in FLEET],"provenance":deepcopy(DATA_PROVENANCE)}

    def reassignment_preview(self, flight_id, crew_id):
        """Real what-if: validate a proposed crew against a flight with the legality engine."""
        flight=next((f for f in FLIGHTS if f["id"]==flight_id),None)
        if not flight: raise WorkflowError(404,"flight_not_found","Flight not found")
        crew_record=next((c for c in CREW_ROSTER if c["id"]==crew_id),None)
        if not crew_record: raise WorkflowError(404,"crew_not_found","Crew member not found")
        meta=ROUTES.get(flight_id)
        if not meta: raise WorkflowError(404,"route_not_found","Planned route not found")
        day=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
        dep_h,dep_m=map(int,meta["proposed"][0].split(":")); arr_h,arr_m=map(int,meta["proposed"][1].split(":"))
        dep=day+timedelta(hours=dep_h,minutes=dep_m); arr=day+timedelta(hours=arr_h,minutes=arr_m)
        if arr<=dep: arr+=timedelta(days=1)
        aircraft=flight["aircraft"]["type"].replace("-8","").replace("neo","")
        qualifications={Qualification.__members__[name] for name in crew_record["qualifications"] if name in Qualification.__members__}
        crew=CrewMember(crew_id,flight["origin"],qualifications,current_location=crew_record["base"],last_rest_end=dep-timedelta(hours=crew_record["rest_hours"]))
        leg=FlightLeg(flight_id,flight["origin"],flight["destination"],dep,arr,aircraft)
        assignment=Assignment(crew_id,[leg],dep-timedelta(minutes=45),arr+timedelta(minutes=20))
        violations=RulesEngine.validate_assignment(crew,assignment)
        required=Qualification.__members__.get(aircraft)
        return {"flight_id":flight_id,"crew_id":crew_id,"crew_name":crew_record["name"],"aircraft_type":flight["aircraft"]["type"],"legal":not violations,"ruleset_version":RulesEngine.RULESET_VERSION,"rule_violations":[v.to_dict() for v in violations],"checks":{"qualified":bool(required and required in qualifications),"positioned_at_origin":crew_record["base"]==flight["origin"],"rest_ok":crew_record["rest_hours"]>=RulesEngine.MIN_REST_HOURS},"provenance":deepcopy(DATA_PROVENANCE)}

    def solver_tiers(self):
        """Run the real solver implementations on the current synthetic India partition."""
        crews,legs=self._scenario_inputs()
        automated_legs,manual_review_legs=self._recovery_scope(legs)
        tier1=solve_tier1(crews,automated_legs,0.5)
        tier2=solve_tier2_detailed(crews,automated_legs,1.0,tier1.assignments)
        tier1_uncovered=[*tier1.uncovered,*manual_review_legs]
        tier2_assignments,tier2_uncovered=tier2.assignments,[*tier2.uncovered,*manual_review_legs]
        tier2_elapsed,tier2_complete=tier2.metadata.elapsed_s,tier2.converged
        total=len(legs)
        return {"generated_at":_now(),"partition_id":"INDIA-NORTH","ruleset_version":RulesEngine.RULESET_VERSION,"data_mode":"executable-synthetic","provenance":deepcopy(DATA_PROVENANCE),"tiers":[
            {"id":"tier1","name":"Immediate Legal Recovery","status":"partial","coverage":len(tier1.assignments)/total,"legal_assignments":len(tier1.assignments),"unresolved":len(tier1_uncovered),"elapsed_s":tier1.elapsed_s,"reason":"Fast legal incumbent; UK945 reserved for scheduler review"},
            {"id":"tier2","name":"Optimization Upgrade","status":tier2.metadata.status,"coverage":len(tier2_assignments)/total,"legal_assignments":len(tier2_assignments),"unresolved":len(tier2_uncovered),"elapsed_s":tier2_elapsed,"reason":tier2.metadata.message,"solver_name":tier2.metadata.solver_name,"objective_value":tier2.metadata.objective_value,"best_bound":tier2.metadata.best_bound,"optimality_gap":tier2.metadata.optimality_gap,"generated_columns":tier2.metadata.generated_columns,"upgraded":tier2.metadata.upgraded},
            {"id":"tier3","name":"Human-Assisted Recovery","status":"ready" if tier2_uncovered else "standby","coverage":1-len(tier2_uncovered)/total,"legal_assignments":0,"unresolved":len(tier2_uncovered),"elapsed_s":0,"reason":"Scheduler queue remains available when automation is incomplete"}
        ]}

    @staticmethod
    def _recovery_scope(legs):
        """Keep one credible case in human review for the presentation scenario.

        UK945 represents a captain-qualification exception requiring scheduler
        acknowledgement.  It remains legal-option searchable, but automated
        tiers cannot silently publish an assignment for it.
        """
        manual=[leg for leg in legs if leg.flight_id=="UK945"]
        automated=[leg for leg in legs if leg.flight_id!="UK945"]
        return automated,manual

    def _scenario_inputs(self):
        day=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
        legs=[]; crews=[]
        for index,flight in enumerate(FLIGHTS):
            meta=ROUTES[flight["id"]]; dh,dm=map(int,meta["proposed"][0].split(":")); ah,am=map(int,meta["proposed"][1].split(":"))
            dep=day+timedelta(hours=dh,minutes=dm); arr=day+timedelta(hours=ah,minutes=am)
            aircraft=flight["aircraft"]["type"].replace("-8","").replace("neo","")
            legs.append(FlightLeg(flight["id"],flight["origin"],flight["destination"],dep,arr,aircraft))
            qualification=Qualification.__members__.get(aircraft)
            crews.append(CrewMember(f"SIM-{index+1:03}",flight["origin"],{qualification} if qualification else set(),current_location=flight["origin"],last_rest_end=dep-timedelta(hours=12)))
        return crews,legs

    @staticmethod
    def _serialize_assignment(assignment):
        return {"crew_id":assignment.crew_id,"duty_start":assignment.duty_start.isoformat(),"duty_end":assignment.duty_end.isoformat(),"flight_legs":[{"flight_id":leg.flight_id,"origin":leg.origin,"destination":leg.destination,"scheduled_dep":leg.scheduled_dep.isoformat(),"scheduled_arr":leg.scheduled_arr.isoformat(),"aircraft_type":leg.aircraft_type,"is_deadhead":leg.is_deadhead} for leg in assignment.flight_legs]}

    def _candidate(self,candidate_id,name,tier,assignments,uncovered,elapsed,crews,recommended):
        crew_by_id={crew.crew_id:crew for crew in crews}; findings=[]
        for assignment in assignments:
            findings.extend(v.to_dict() for v in RulesEngine.validate_assignment(crew_by_id[assignment.crew_id],assignment))
        covered=sum(len([leg for leg in assignment.flight_legs if not leg.is_deadhead]) for assignment in assignments)
        total=covered+len(uncovered); coverage=covered/total if total else 1
        return {"id":candidate_id,"name":name,"recommended":recommended,"legal":not findings,"coverage":coverage,"flights_recovered":covered,"total_delay":sum(f["delay"] for f in FLIGHTS if f["id"] in {leg.flight_id for assignment in assignments for leg in assignment.flight_legs}),"max_delay":max((f["delay"] for f in FLIGHTS),default=0),"illegal_crews":len(findings),"aircraft_swaps":0,"gate_conflicts":0,"misconnections":sum(f["connections"] for f in FLIGHTS if f["id"] in {leg.flight_id for leg in uncovered}),"passengers_recovered":sum(f["passengers"] for f in FLIGHTS if f["id"] in {leg.flight_id for assignment in assignments for leg in assignment.flight_legs}),"cost":round(sum((a.duty_end-a.duty_start).total_seconds()/3600 for a in assignments)*100000),"risk":"low" if not uncovered and not findings else "medium","warnings":[v["message"] for v in findings]+[f"{len(uncovered)} unresolved flights" for _ in [0] if uncovered],"changes":[f"Assign {a.crew_id} to {', '.join(l.flight_id for l in a.flight_legs)}" for a in assignments],"tier":tier,"solver_version":"skysolver-demo-2026.08","input_snapshot_id":f"SNP-{uuid.uuid4().hex[:12].upper()}","ruleset_version":RulesEngine.RULESET_VERSION,"state_version":DATA_PROVENANCE["state_version"],"elapsed_s":elapsed,"assignments":[self._serialize_assignment(a) for a in assignments],"crew_snapshot":{crew.crew_id:{"base_hub":crew.base_hub,"current_location":crew.current_location,"last_rest_end":crew.last_rest_end.isoformat() if crew.last_rest_end else None,"qualifications":[q.name for q in crew.qualifications]} for crew in crews},"legality_certificate":{"valid":not findings,"findings":findings,"validated_at":_now()},"joint_feasibility":{"status":"not_evaluated","deployable":False,"findings":[{"code":"AUTHORITATIVE_RESOURCE_DATA_REQUIRED","blocking":True,"message":"Crew complement, aircraft, airport and passenger source records are not connected"}]},"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),"deployment_readiness":"simulation_only"}

    def create(self, payload):
        with self._lock:
            rid = f"RCV-{uuid.uuid4().hex[:8].upper()}"
            crews,legs=self._scenario_inputs(); automated_legs,manual_review_legs=self._recovery_scope(legs)
            tier1=solve_tier1(crews,automated_legs,0.5)
            tier2=solve_tier2_detailed(crews,automated_legs,1.0,tier1.assignments)
            tier1_uncovered=[*tier1.uncovered,*manual_review_legs]
            tier2_uncovered=[*tier2.uncovered,*manual_review_legs]
            tier1_id=f"CAN-{uuid.uuid4().hex[:16].upper()}"; tier2_id=f"CAN-{uuid.uuid4().hex[:16].upper()}"
            tier2_name="Restricted MILP upgrade" if tier2.metadata.upgraded else "Tier 1 incumbent retained — no MILP upgrade"
            candidates=[self._candidate(tier1_id,"Immediate legal incumbent","tier1",tier1.assignments,tier1_uncovered,tier1.elapsed_s,crews,not tier2.metadata.upgraded),self._candidate(tier2_id,tier2_name,"tier2",tier2.assignments,tier2_uncovered,tier2.metadata.elapsed_s,crews,tier2.metadata.upgraded)]
            candidates[-1]["optimization_metadata"]={"status":tier2.metadata.status,"solver_name":tier2.metadata.solver_name,"objective_value":tier2.metadata.objective_value,"best_bound":tier2.metadata.best_bound,"optimality_gap":tier2.metadata.optimality_gap,"generated_columns":tier2.metadata.generated_columns,"upgraded":tier2.metadata.upgraded,"message":tier2.metadata.message}
            assigned_crew_ids={assignment.crew_id for assignment in tier2.assignments}
            tier3_crew_pool=[crew for crew in crews if crew.crew_id not in assigned_crew_ids]
            tier3_suggestions=[item.to_dict() for item in generate_suggestions(tier2_uncovered,tier3_crew_pool,payload.get("partition_id","DEL"),1)]
            recovery = {"id": rid, "disruption_id": payload.get("disruption_id", DISRUPTIONS[0]["id"]), "partition_id": payload.get("partition_id", "DEL"), "objective": payload.get("objective", "balanced"), "status": "awaiting_intervention", "stage": "tier3_scheduler_review", "tier": "tier3", "progress": round(max(c["coverage"] for c in candidates)*100), "state_version": 1, "selected_candidate_id": None, "validated": False, "deployed": False, "proposed_by": payload.get("operator_id", "system"), "approvals": [], "created_at": _now(), "updated_at": _now(), "candidates": candidates, "tier3":{"status":"ready","unresolved_flight_ids":[f.flight_id for f in tier2_uncovered],"suggestions":tier3_suggestions}, "acknowledgements": [],"provenance":deepcopy(DATA_PROVENANCE),"carrier_writes_enabled":self._carrier_writes_enabled}
            # A new recovery for the same disruption supersedes the earlier ones.
            # Their resource holds must be released, or the crew, aircraft and
            # gates they reserved stay locked and this recovery can never select
            # a candidate that needs them.
            released = self._supersede_prior_recoveries(recovery["disruption_id"], rid)
            self._recoveries[rid] = recovery
            self._record(rid, "recovery_created", "system", f"Executable synthetic solve produced {len(candidates)} candidates")
            if released:
                self._record(rid, "holds_released", "system", f"Superseded {len(released)} prior recovery hold(s)")
            self._persist()
            return self.envelope("awaiting_review", 1, correlation_id=payload.get("correlation_id"), causation_id=payload.get("causation_id"), recovery=deepcopy(recovery))

    def get(self, recovery_id):
        if recovery_id not in self._recoveries:
            raise WorkflowError(404, "not_found", "Recovery not found")
        return deepcopy(self._recoveries[recovery_id])

    def candidates(self, recovery_id):
        return self.get(recovery_id)["candidates"]

    def tier3_suggestions(self, recovery_id, offset=0, limit=50):
        recovery=self.get(recovery_id); suggestions=recovery.get("tier3",{}).get("suggestions",[])
        offset=max(0,int(offset)); limit=min(200,max(1,int(limit)))
        return {"items":deepcopy(suggestions[offset:offset+limit]),"offset":offset,"limit":limit,"total":len(suggestions),"state_version":recovery["state_version"],"status":recovery.get("tier3",{}).get("status","standby")}

    def decide_tier3_suggestion(self,recovery_id,suggestion_id,payload):
        with self._lock:
            recovery=self._recoveries.get(recovery_id)
            if not recovery: raise WorkflowError(404,"not_found","Recovery not found")
            self._version(recovery,payload)
            suggestion=next((item for item in recovery.get("tier3",{}).get("suggestions",[]) if item["suggestion_id"]==suggestion_id),None)
            if not suggestion: raise WorkflowError(404,"suggestion_not_found","Tier 3 suggestion not found")
            action=payload.get("action"); reason=str(payload.get("reason","")).strip()
            if action in {"reject","hold","edit"} and not reason:
                raise WorkflowError(422,"reason_required",f"Tier 3 {action} requires a reason")
            if action=="request_more_options":
                crews,legs=self._scenario_inputs(); unresolved_ids=set(recovery.get("tier3",{}).get("unresolved_flight_ids",[]))
                generated=generate_suggestions([leg for leg in legs if leg.flight_id in unresolved_ids],crews,recovery["partition_id"],recovery["state_version"]+1)
                known={item["suggestion_id"] for item in recovery["tier3"]["suggestions"]}
                recovery["tier3"]["suggestions"].extend(item.to_dict() for item in generated if item.suggestion_id not in known)
            elif action=="edit":
                crew_id=str(payload.get("crew_id") or suggestion["crew_id"]); flight_id=str(payload.get("flight_id") or suggestion["proposed_flight_ids"][0])
                crews,legs=self._scenario_inputs(); crew=next((item for item in crews if item.crew_id==crew_id),None); leg=next((item for item in legs if item.flight_id==flight_id),None)
                if not crew or not leg: raise WorkflowError(422,"edit_reference_invalid","Edited crew and flight must exist in the recovery snapshot")
                edited=generate_suggestions([leg],[crew],recovery["partition_id"],recovery["state_version"]+1)
                if not edited: raise WorkflowError(422,"illegal_suggestion_edit","Edited assignment failed legality validation")
                replacement=edited[0].to_dict(); replacement["reason"]=reason; replacement["supersedes_suggestion_id"]=suggestion_id
                suggestion.update({"status":SuggestionStatus.SUPERSEDED.value,"superseded_by_suggestion_id":replacement["suggestion_id"],"decision_reason":reason})
                recovery["tier3"]["suggestions"].append(replacement)
            else:
                status={"approve":SuggestionStatus.APPROVED.value,"reject":SuggestionStatus.REJECTED.value,"hold":SuggestionStatus.HELD.value}.get(action)
                if not status: raise WorkflowError(422,"action_invalid","Tier 3 action must be approve, reject, hold, edit or request_more_options")
                suggestion.update({"status":status,"approved_by":payload.get("operator_id"),"approved_at":_now(),"decision_reason":reason})
                if action=="approve":
                    crews,legs=self._scenario_inputs(); crew_ids={suggestion["crew_id"]}; flight_ids=set(suggestion["proposed_flight_ids"])
                    selected_crews=[item for item in crews if item.crew_id in crew_ids]; selected_legs=[item for item in legs if item.flight_id in flight_ids]
                    crew=selected_crews[0]; assignment=Assignment(crew.crew_id,selected_legs,min(x.scheduled_dep for x in selected_legs),max(x.scheduled_arr for x in selected_legs))
                    unresolved_ids=set(recovery.get("tier3",{}).get("unresolved_flight_ids",[]))-flight_ids
                    automated_legs,_=self._recovery_scope(legs)
                    incumbent=solve_tier1(crews,automated_legs,0.5)
                    combined=[*incumbent.assignments,assignment]
                    remaining=[item for item in legs if item.flight_id in unresolved_ids]
                    candidate=self._candidate(f"CAN-{uuid.uuid4().hex[:16].upper()}","Scheduler-completed recovery plan","tier3",combined,remaining,incumbent.elapsed_s,crews,True)
                    candidate["source_suggestion_id"]=suggestion_id; recovery["candidates"].append(candidate)
                    recovery["progress"]=round(candidate["coverage"]*100)
                    recovery["status"]="awaiting_review"
                    recovery["stage"]="candidate_comparison"
                    recovery["tier"]="tier3"
            recovery["state_version"]+=1; recovery["updated_at"]=_now()
            self._record(recovery_id,f"tier3_suggestion_{action}",payload.get("operator_id","scheduler-demo"),reason or suggestion_id)
            self._persist()
            return self.envelope("tier3_updated",recovery["state_version"],correlation_id=payload.get("correlation_id"),causation_id=payload.get("causation_id"),recovery=deepcopy(recovery))

    def _supersede_prior_recoveries(self, disruption_id, new_recovery_id):
        """Mark earlier recoveries for this disruption superseded and free their holds."""
        released = []
        for rid, prior in self._recoveries.items():
            if rid == new_recovery_id or prior.get("disruption_id") != disruption_id:
                continue
            if prior.get("status") != "superseded":
                prior["status"] = "superseded"
                prior["updated_at"] = _now()
            released.extend(self._hold_registry.release_all_for_recovery(rid))
        return released

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
            if action != "reject":
                resources = []
                for assignment in candidate["assignments"]:
                    resources.append(f"crew:{assignment['crew_id']}")
                    for leg in assignment["flight_legs"]:
                        flight = next(item for item in FLIGHTS if item["id"] == leg["flight_id"])
                        resources.extend([f"flight:{flight['id']}", f"aircraft:{flight['aircraft']['registration']}", f"gate:{flight['origin']}:{flight['proposed_gate']}", f"passenger-inventory:{flight['id']}"])
                try:
                    hold = self._hold_registry.acquire(tenant_id="synthetic-airline", recovery_id=recovery_id,
                        candidate_id=candidate["id"], candidate_version=candidate["state_version"], resources=resources,
                        owner=payload.get("operator_id", "scheduler-demo"), ttl_seconds=600)
                except HoldConflict as exc:
                    raise WorkflowError(409 if exc.code == "resource_conflict" else 422, exc.code, f"{exc}: {', '.join(exc.resources)}") from exc
                candidate["resource_hold"] = hold.to_dict()
            elif candidate.get("resource_hold"):
                try:
                    self._hold_registry.release_for_recovery(candidate["resource_hold"]["hold_id"], recovery_id)
                except HoldConflict:
                    pass
                candidate["resource_hold"] = None
            next_status = "held" if action == "hold" else ("validating" if action != "reject" else "awaiting_review")
            next_stage = "candidate_held" if action == "hold" else ("rule_validation" if action != "reject" else "candidate_comparison")
            recovery.update({"selected_candidate_id": candidate["id"] if action != "reject" else None, "status": next_status, "stage": next_stage, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, f"candidate_{action}", payload.get("operator_id", "ops-controller"), payload.get("reason") or candidate["name"])
            self._persist()
            return self.envelope(recovery["status"], recovery["state_version"], correlation_id=payload.get("correlation_id"), causation_id=payload.get("causation_id"), recovery=deepcopy(recovery))

    def validate(self, recovery_id, payload):
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["selected_candidate_id"]:
                raise WorkflowError(422, "candidate_required", "Select a candidate before validation")
            candidate = next(c for c in recovery["candidates"] if c["id"] == recovery["selected_candidate_id"])
            hold = candidate.get("resource_hold")
            if not hold:
                raise WorkflowError(422, "resource_hold_required", "Candidate resources must be held before validation")
            try:
                self._hold_registry.assert_current(hold["hold_id"], candidate["id"], candidate["state_version"])
            except HoldConflict as exc:
                raise WorkflowError(409, exc.code, str(exc)) from exc
            crew_snapshot=candidate["crew_snapshot"]; findings=[]
            for stored in candidate["assignments"]:
                profile=crew_snapshot[stored["crew_id"]]
                crew=CrewMember(stored["crew_id"],profile["base_hub"],{Qualification[name] for name in profile["qualifications"]},current_location=profile["current_location"],last_rest_end=datetime.fromisoformat(profile["last_rest_end"]) if profile["last_rest_end"] else None)
                legs=[FlightLeg(item["flight_id"],item["origin"],item["destination"],datetime.fromisoformat(item["scheduled_dep"]),datetime.fromisoformat(item["scheduled_arr"]),item["aircraft_type"],item["is_deadhead"]) for item in stored["flight_legs"]]
                assignment=Assignment(stored["crew_id"],legs,datetime.fromisoformat(stored["duty_start"]),datetime.fromisoformat(stored["duty_end"]))
                findings.extend(v.to_dict() for v in RulesEngine.validate_assignment(crew,assignment))
            if findings:
                raise WorkflowError(422, "illegal_plan", findings[0]["message"])
            certificate_candidate={"assignments":candidate["assignments"],"input_snapshot_id":candidate["input_snapshot_id"],"candidate_id":candidate["id"],"state_version":candidate["state_version"]}
            rules_package={"ruleset_version":RulesEngine.RULESET_VERSION,"certification":"dgca-oriented-demo-not-certified"}
            signed_certificate=self._certificate_issuer.issue(tenant_id="synthetic-airline",recovery_id=recovery_id,candidate_id=candidate["id"],input_snapshot=candidate["crew_snapshot"],candidate=certificate_candidate,rules_package=rules_package,ruleset_version=RulesEngine.RULESET_VERSION,state_version=recovery["state_version"],findings=[])
            candidate["legality_certificate"]={**signed_certificate.to_dict(),"findings":[],"independent":False,"warning":"Demo in-process validation; not an independently deployed certified service"}
            recovery.update({"validated": True, "status": "awaiting_joint_feasibility", "stage": "demo_legality_validated", "progress": 90, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "legality_validated", payload.get("operator_id", "scheduler"), f"{len(candidate['assignments'])} assignments validated against the non-certified DGCA-oriented ruleset")
            self._persist()
            return self.envelope("awaiting_joint_feasibility", recovery["state_version"], correlation_id=payload.get("correlation_id"), causation_id=payload.get("causation_id"), recovery=deepcopy(recovery))

    def approve(self, recovery_id, payload):
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["validated"]:
                raise WorkflowError(422, "validation_required", "Demo legality validation must complete before approval")
            approver = str(payload.get("operator_id", ""))
            if not approver:
                raise WorkflowError(401, "identity_required", "Approval requires a server-derived identity")
            if payload.get("operator_role") != "duty-manager":
                raise WorkflowError(403, "approval_role_required", "Only a duty manager may approve a recovery plan")
            if approver == recovery.get("proposed_by"):
                raise WorkflowError(403, "segregation_of_duties", "The proposer cannot approve the same recovery plan")
            approval = {"id": str(uuid.uuid4()), "actor": approver, "role": payload.get("operator_role"), "reason": str(payload.get("reason", "")).strip(), "timestamp": _now(), "candidate_id": recovery["selected_candidate_id"], "state_version": recovery["state_version"]}
            if not approval["reason"]:
                raise WorkflowError(422, "reason_required", "Approval requires a reason")
            recovery["approvals"].append(approval)
            recovery.update({"status": "approved", "stage": "awaiting_deployment", "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "plan_approved", approver, approval["reason"])
            self._persist()
            return self.envelope("approved", recovery["state_version"], correlation_id=payload.get("correlation_id"), causation_id=payload.get("causation_id"), recovery=deepcopy(recovery))

    def deploy(self, recovery_id, payload, idempotency_key):
        with self._lock:
            if not self._carrier_writes_enabled:
                raise WorkflowError(403, "carrier_writes_disabled", "Carrier publishing is disabled until shadow-pilot safety gates are approved")
            if idempotency_key and idempotency_key in self._idempotency:
                return deepcopy(self._idempotency[idempotency_key])
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["validated"]:
                raise WorkflowError(422, "validation_required", "Plan must pass legality validation")
            if not recovery.get("approvals"):
                raise WorkflowError(422, "approval_required", "A duty-manager approval is required before deployment")
            candidate = next(item for item in recovery["candidates"] if item["id"] == recovery["selected_candidate_id"])
            if not candidate.get("joint_feasibility", {}).get("deployable", False):
                raise WorkflowError(422, "joint_feasibility_required", "Authoritative crew, aircraft, airport and passenger feasibility must pass before deployment")
            certificate_data = candidate.get("legality_certificate") or {}
            try:
                certificate = LegalityCertificate(**{key: value for key, value in certificate_data.items() if key in LegalityCertificate.__dataclass_fields__})
            except TypeError as exc:
                raise WorkflowError(422, "legality_certificate_required", "Candidate has no complete legality certificate") from exc
            certificate_candidate={"assignments":candidate["assignments"],"input_snapshot_id":candidate["input_snapshot_id"],"candidate_id":candidate["id"],"state_version":candidate["state_version"]}
            rules_package={"ruleset_version":RulesEngine.RULESET_VERSION,"certification":"dgca-oriented-demo-not-certified"}
            if not self._certificate_issuer.verify(certificate,input_snapshot=candidate["crew_snapshot"],candidate=certificate_candidate,rules_package=rules_package):
                raise WorkflowError(422, "legality_certificate_invalid", "Candidate legality certificate does not match current artifacts")
            resources = []
            for assignment in candidate["assignments"]:
                resources.append({"resource_type": "crew", "resource_id": assignment["crew_id"], "target_system": "crew-operations-adapter", "action": "publish_assignment", "reversible": True})
            for flight_id in {leg["flight_id"] for assignment in candidate["assignments"] for leg in assignment["flight_legs"]}:
                flight = next(item for item in FLIGHTS if item["id"] == flight_id)
                resources.extend([
                    {"resource_type": "aircraft", "resource_id": flight["aircraft"]["registration"], "target_system": "aircraft-operations-adapter", "action": "publish_rotation", "reversible": True},
                    {"resource_type": "gate", "resource_id": f"{flight['origin']}:{flight['proposed_gate']}", "target_system": "aodb-adapter", "action": "publish_gate", "reversible": True},
                    {"resource_type": "passenger", "resource_id": flight_id, "target_system": "passenger-service-adapter", "action": "publish_recovery", "reversible": False},
                ])
            deployment = self._deployment_registry.create(tenant_id="synthetic-airline", recovery_id=recovery_id,
                candidate_id=candidate["id"], candidate_version=candidate["state_version"], idempotency_key=idempotency_key,
                correlation_id=str(payload.get("correlation_id") or uuid.uuid4()), requested_by=payload.get("operator_id", "deployment-controller"), resources=resources)
            acknowledgements = [{"resource": f"{item.resource_type}:{item.resource_id}", "command_id": item.command_id, "status": item.status.value} for item in deployment.commands]
            recovery.update({"deployed": False, "deployment_id": deployment.deployment_id, "status": "deploying", "stage": "awaiting_acknowledgements", "progress": 95, "acknowledgements": acknowledgements, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "deployment_queued", payload.get("operator_id", "deployment-controller"), deployment.deployment_id)
            result = self.envelope("deploying", recovery["state_version"], correlation_id=payload.get("correlation_id"), causation_id=payload.get("causation_id"), recovery=deepcopy(recovery), deployment=deployment.to_dict(), acknowledgements=acknowledgements)
            if idempotency_key:
                self._idempotency[idempotency_key] = deepcopy(result)
            self._persist()
            return result

    def simulate_deployment(self, recovery_id, payload):
        """Shadow deployment: run the real command state machine against synthetic
        adapters to produce per-resource acknowledgements, without a live carrier
        publish. Used to demonstrate the deployment orchestration end to end."""
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery.get("selected_candidate_id"):
                raise WorkflowError(422, "candidate_required", "Select a candidate before deployment")
            if not recovery["validated"]:
                raise WorkflowError(422, "validation_required", "Validate the plan before deployment")
            if not recovery.get("approvals"):
                raise WorkflowError(422, "approval_required", "A duty-manager approval is required before deployment")
            candidate = next(item for item in recovery["candidates"] if item["id"] == recovery["selected_candidate_id"])
            resources = []
            for assignment in candidate["assignments"]:
                resources.append({"resource_type": "crew", "resource_id": assignment["crew_id"], "target_system": "crew-operations-adapter", "action": "publish_assignment", "reversible": True})
            for flight_id in {leg["flight_id"] for assignment in candidate["assignments"] for leg in assignment["flight_legs"]}:
                flight = next(item for item in FLIGHTS if item["id"] == flight_id)
                resources.extend([
                    {"resource_type": "aircraft", "resource_id": flight["aircraft"]["registration"], "target_system": "aircraft-operations-adapter", "action": "publish_rotation", "reversible": True},
                    {"resource_type": "gate", "resource_id": f"{flight['origin']}:{flight['proposed_gate']}", "target_system": "aodb-adapter", "action": "publish_gate", "reversible": True},
                    {"resource_type": "passenger", "resource_id": flight_id, "target_system": "passenger-service-adapter", "action": "publish_recovery", "reversible": False},
                ])
            deployment = self._deployment_registry.create(tenant_id="synthetic-airline", recovery_id=recovery_id,
                candidate_id=candidate["id"], candidate_version=candidate["state_version"], idempotency_key=payload.get("idempotency_key") or str(uuid.uuid4()),
                correlation_id=str(payload.get("correlation_id") or uuid.uuid4()), requested_by=payload.get("operator_id", "deployment-controller"), resources=resources)
            # Drive the command state machine: every resource acknowledges, so the
            # deployment completes across crew, aircraft, gate and passenger adapters.
            dep = deployment
            cmds = list(deployment.commands)
            reference = deployment.deployment_id
            for idx, cmd in enumerate(cmds):
                dep = self._deployment_registry.mark_sent(reference, cmd.command_id, dep.state_version, f"ADP-{idx:03d}")
            for idx, cmd in enumerate(cmds):
                dep = self._deployment_registry.acknowledge(reference, cmd.command_id, dep.state_version, accepted=True, adapter_reference=f"ADP-{idx:03d}")
            deployment = self._deployment_registry.get(reference)
            acknowledgements = [{"resource": f"{item.resource_type}:{item.resource_id}", "command_id": item.command_id, "status": item.status.value, "detail": item.failure_detail, "target_reference": item.adapter_reference} for item in deployment.commands]
            recovery.update({"deployment_id": deployment.deployment_id, "deployment_status": deployment.status.value, "status": "deployed", "stage": "acknowledged", "progress": 100, "acknowledgements": acknowledgements, "simulated": True, "deployed": True, "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "shadow_deployment_simulated", payload.get("operator_id", "controller"), deployment.deployment_id)
            self._persist()
            return self.envelope("shadow_deployed", recovery["state_version"], correlation_id=payload.get("correlation_id"), causation_id=payload.get("causation_id"), recovery=deepcopy(recovery), deployment=deployment.to_dict(), acknowledgements=acknowledgements)

    def deployment(self, deployment_id):
        try:
            return deepcopy(self._deployment_registry.get(deployment_id).to_dict())
        except DeploymentConflict as exc:
            raise WorkflowError(404, exc.code, str(exc)) from exc

    def send_deployment_command(self, deployment_id, command_id, expected_version, adapter_reference):
        try:
            deployment = self._deployment_registry.mark_sent(deployment_id, command_id, expected_version, adapter_reference)
            return deepcopy(deployment.to_dict())
        except DeploymentConflict as exc:
            raise WorkflowError(409 if exc.code == "stale_state" else 422, exc.code, str(exc)) from exc

    def acknowledge_deployment_command(self, deployment_id, command_id, expected_version, accepted, adapter_reference, failure_code=None, failure_detail=None):
        try:
            deployment = self._deployment_registry.acknowledge(deployment_id, command_id, expected_version, accepted=accepted, adapter_reference=adapter_reference, failure_code=failure_code, failure_detail=failure_detail)
        except DeploymentConflict as exc:
            raise WorkflowError(409 if exc.code == "stale_state" else 422, exc.code, str(exc)) from exc
        recovery = self._recoveries[deployment.recovery_id]
        recovery["acknowledgements"] = [{"resource": f"{item.resource_type}:{item.resource_id}", "command_id": item.command_id, "status": item.status.value} for item in deployment.commands]
        if deployment.status is DeploymentStatus.COMPLETE:
            recovery.update({"deployed": True, "status": "deployed", "stage": "recovered", "progress": 100})
            self._record(recovery["id"], "deployment_completed", "adapter-reconciliation", deployment.deployment_id)
        elif deployment.status in {DeploymentStatus.PARTIAL, DeploymentStatus.FAILED}:
            recovery.update({"deployed": False, "status": "partially_deployed" if deployment.status is DeploymentStatus.PARTIAL else "deployment_failed", "stage": "reconciliation_required"})
        recovery["updated_at"] = _now(); self._persist()
        return deepcopy(deployment.to_dict())

    def retry_deployment_command(self, deployment_id, command_id, expected_version):
        try:
            deployment = self._deployment_registry.retry(deployment_id, command_id, expected_version)
            return deepcopy(deployment.to_dict())
        except DeploymentConflict as exc:
            raise WorkflowError(409 if exc.code == "stale_state" else 422, exc.code, str(exc)) from exc

    def compensate_deployment(self, deployment_id, expected_version, operator_id, reason):
        try:
            deployment = self._deployment_registry.compensate(deployment_id, expected_version)
        except DeploymentConflict as exc:
            raise WorkflowError(409 if exc.code == "stale_state" else 422, exc.code, str(exc)) from exc
        recovery = self._recoveries[deployment.recovery_id]
        requires_new = deployment.status is DeploymentStatus.REQUIRES_NEW_RECOVERY
        recovery.update({"deployed": True, "validated": False, "status": "requires_new_recovery" if requires_new else "compensating", "stage": "irreversible_action" if requires_new else "compensation_pending", "state_version": recovery["state_version"] + 1, "updated_at": _now()})
        self._record(recovery["id"], "compensation_requested", operator_id, reason)
        self._persist()
        return self.envelope(recovery["status"], recovery["state_version"], recovery=deepcopy(recovery), deployment=deployment.to_dict())

    def rollback(self, recovery_id, payload):
        with self._lock:
            recovery = self._recoveries.get(recovery_id)
            if not recovery:
                raise WorkflowError(404, "not_found", "Recovery not found")
            self._version(recovery, payload)
            if not recovery["deployed"]:
                raise WorkflowError(422, "not_deployed", "Only deployed plans can be rolled back")
            try:
                deployment = self._deployment_registry.compensate(recovery["deployment_id"], self._deployment_registry.get(recovery["deployment_id"]).state_version)
            except DeploymentConflict as exc:
                raise WorkflowError(422, exc.code, str(exc)) from exc
            requires_new = deployment.status is DeploymentStatus.REQUIRES_NEW_RECOVERY
            recovery.update({"deployed": True, "validated": False, "status": "requires_new_recovery" if requires_new else "compensating", "stage": "irreversible_action" if requires_new else "compensation_pending", "state_version": recovery["state_version"] + 1, "updated_at": _now()})
            self._record(recovery_id, "compensation_requested", payload.get("operator_id", "deployment-controller"), payload.get("reason", "Operational compensation"))
            self._persist()
            return self.envelope(recovery["status"], recovery["state_version"], recovery=deepcopy(recovery), deployment=deployment.to_dict())

    def audit(self):
        return deepcopy(list(reversed(self._audit)))

    def events(self):
        return deepcopy(self._audit[-50:])

    def _record(self, recovery_id, action, operator, detail):
        self._audit.append({"id": str(uuid.uuid4()), "recovery_id": recovery_id, "action": action, "operator": operator, "detail": detail, "timestamp": _now(), "ruleset_version": RulesEngine.RULESET_VERSION})

    def note(self, action, operator, detail, recovery_id="SCENARIO"):
        """Append an operator action to the audit trail (used by interactive UI steps)."""
        with self._lock:
            self._record(recovery_id, str(action)[:64], str(operator or "operator")[:64], str(detail or "")[:280])
            self._persist()
        return {"ok": True, "action": action}


recovery_store = RecoveryStore(os.environ.get("SKYSOLVER_RECOVERY_STATE", ".sky_recovery_state.json"))
