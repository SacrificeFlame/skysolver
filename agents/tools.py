"""Tool surface exposed to the recovery agent.

Every tool is a thin, audited wrapper over the existing ``RecoveryStore``.  The
agent has no other way to touch the domain, which gives us two properties that
matter more than the planner itself:

1. **The legality engine is not bypassable.**  ``commit_reassignment`` refuses
   unless this run already obtained a *legal* verdict from
   ``preview_reassignment`` for that exact (flight, crew) pair.  The check lives
   here, in code — not in a system prompt — so a hallucinating or adversarial
   planner still cannot publish an illegal roster.

2. **Escalation is earned, not asserted.**  ``escalate_to_tier3`` refuses until
   every type-rated candidate for the flight has actually been evaluated and
   rejected by the engine.

The JSON schemas below are the same objects handed to the Claude tool-use API
by the LLM planner, so the deterministic and LLM planners see an identical
surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from deployment.recovery_api import CREW_ROSTER, FLIGHTS, WorkflowError


# --------------------------------------------------------------------------
# Domain helpers
# --------------------------------------------------------------------------

def normalise_aircraft_type(aircraft_type: str) -> str:
    """Map a fleet type to the qualification family the rules engine uses.

    Mirrors ``RecoveryStore.reassignment_preview`` so the shortlist and the
    verdict agree on what "type rated" means (A321neo -> A321, B787-8 -> B787).
    """
    return aircraft_type.replace("-8", "").replace("neo", "")


def flight_record(flight_id: str) -> Optional[dict]:
    return next((f for f in FLIGHTS if f["id"] == flight_id), None)


def crew_record(crew_id: str) -> Optional[dict]:
    return next((c for c in CREW_ROSTER if c["id"] == crew_id), None)


def type_rated_candidates(flight_id: str) -> List[dict]:
    """Unassigned crew holding the type rating this flight requires.

    Shortlisting is deliberately limited to the type rating.  Rest, positioning
    and duty limits are the rules engine's call, not ours — we must not
    pre-judge legality or the trace would be showing our opinion instead of the
    regulator's.
    """
    flight = flight_record(flight_id)
    if not flight:
        return []
    required = normalise_aircraft_type(flight["aircraft"]["type"])
    return [
        crew
        for crew in CREW_ROSTER
        if crew.get("assigned_flight") is None and required in crew["qualifications"]
    ]


def open_crew_cases() -> List[dict]:
    """Flights whose assigned crew is currently out of legal limits."""
    cases = []
    for crew in CREW_ROSTER:
        if crew.get("status") != "illegal" or not crew.get("assigned_flight"):
            continue
        flight = flight_record(crew["assigned_flight"])
        if not flight:
            continue
        cases.append(
            {
                "flight_id": flight["id"],
                "route": f"{flight['origin']}-{flight['destination']}",
                "aircraft_type": flight["aircraft"]["type"],
                "required_qualification": normalise_aircraft_type(flight["aircraft"]["type"]),
                "incumbent_crew_id": crew["id"],
                "incumbent_crew_name": crew["name"],
                "incumbent_duty_remaining": crew["duty_remaining"],
                "passengers": flight["passengers"],
                "connections": flight["connections"],
                "delay_minutes": flight["delay"],
                "risk": flight["risk"],
            }
        )
    return cases


# --------------------------------------------------------------------------
# Tool plumbing
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Dict[str, Any]]


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"tool": self.tool, "ok": self.ok}
        if self.ok:
            payload["data"] = self.data
        else:
            payload["error"] = self.error
        return payload


class ToolRegistry:
    """Per-run tool surface, including the non-bypassable legality guard."""

    def __init__(self, store):
        self._store = store
        self._specs: Dict[str, ToolSpec] = {}
        # Guard state, accumulated over the run.
        self._legal_previews: set[Tuple[str, str]] = set()
        self._previewed: Dict[str, set[str]] = {}
        self._verdicts: Dict[Tuple[str, str], dict] = {}
        self.commitments: List[dict] = []
        self.escalations: List[dict] = []
        self.call_count = 0

    # -- registration ------------------------------------------------------
    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def names(self) -> List[str]:
        return list(self._specs)

    def anthropic_tools(self) -> List[Dict[str, Any]]:
        """Tool definitions in Claude tool-use format (used by the LLM planner)."""
        return [
            {"name": s.name, "description": s.description, "input_schema": s.input_schema}
            for s in self._specs.values()
        ]

    # -- invocation --------------------------------------------------------
    def run(self, name: str, **kwargs: Any) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(tool=name, ok=False, error=f"Unknown tool '{name}'")
        self.call_count += 1
        try:
            return ToolResult(tool=name, ok=True, data=spec.handler(**kwargs))
        except WorkflowError as exc:  # domain-level rejection from the store
            return ToolResult(tool=name, ok=False, error=f"{exc.code}: {exc.message}")
        except GuardRejection as exc:
            return ToolResult(tool=name, ok=False, error=str(exc))
        except TypeError as exc:  # bad tool arguments from a planner
            return ToolResult(tool=name, ok=False, error=f"invalid_arguments: {exc}")

    # -- guard state (read by the planners) --------------------------------
    def previewed_crew(self, flight_id: str) -> set[str]:
        return set(self._previewed.get(flight_id, set()))

    def verdict(self, flight_id: str, crew_id: str) -> Optional[dict]:
        return self._verdicts.get((flight_id, crew_id))

    def has_legal_option(self, flight_id: str) -> bool:
        return any(f == flight_id for f, _ in self._legal_previews)


class GuardRejection(Exception):
    """Raised when a tool call would violate an invariant of the workflow."""


def build_registry(store, operator: str = "recovery-agent") -> ToolRegistry:
    """Wire the tool surface for one agent run."""
    registry = ToolRegistry(store)

    # -- 1. Perceive -------------------------------------------------------
    def get_operational_picture() -> Dict[str, Any]:
        cases = open_crew_cases()
        for case in cases:
            case["type_rated_candidates"] = len(type_rated_candidates(case["flight_id"]))
        return {
            "disruptions": store.disruptions(),
            "open_crew_cases": cases,
            "open_case_count": len(cases),
            "standby_pool_size": sum(
                1 for c in CREW_ROSTER if c.get("assigned_flight") is None
            ),
            "resolved_this_run": [c["flight_id"] for c in registry.commitments],
            "escalated_this_run": [e["flight_id"] for e in registry.escalations],
        }

    registry.register(
        ToolSpec(
            name="get_operational_picture",
            description=(
                "Read the current disruption state: active disruptions, every flight whose "
                "assigned crew is out of legal limits, and how many type-rated replacements "
                "exist for each. Call this first."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=get_operational_picture,
        )
    )

    # -- 2. Shortlist ------------------------------------------------------
    def list_candidate_crew(flight_id: str) -> Dict[str, Any]:
        flight = flight_record(flight_id)
        if not flight:
            raise WorkflowError(404, "flight_not_found", f"Unknown flight {flight_id}")
        seen = registry.previewed_crew(flight_id)
        candidates = []
        for crew in type_rated_candidates(flight_id):
            candidates.append(
                {
                    "crew_id": crew["id"],
                    "name": crew["name"],
                    "rank": crew["rank"],
                    "base": crew["base"],
                    "qualifications": list(crew["qualifications"]),
                    "rest_hours": crew["rest_hours"],
                    "duty_remaining": crew["duty_remaining"],
                    "seniority": crew["seniority"],
                    "already_evaluated": crew["id"] in seen,
                }
            )
        return {
            "flight_id": flight_id,
            "origin": flight["origin"],
            "required_qualification": normalise_aircraft_type(flight["aircraft"]["type"]),
            "candidates": candidates,
            "candidate_count": len(candidates),
            "note": (
                "Shortlisted on type rating only. Rest, positioning and duty limits are "
                "decided by preview_reassignment, not by this list."
            ),
        }

    registry.register(
        ToolSpec(
            name="list_candidate_crew",
            description=(
                "List unassigned crew who hold the type rating a flight requires. This is a "
                "shortlist, not a legality verdict — you must still preview each candidate."
            ),
            input_schema={
                "type": "object",
                "properties": {"flight_id": {"type": "string", "description": "e.g. AI807"}},
                "required": ["flight_id"],
            },
            handler=list_candidate_crew,
        )
    )

    # -- 3. Act (the legality gate) ---------------------------------------
    def preview_reassignment(flight_id: str, crew_id: str) -> Dict[str, Any]:
        verdict = store.reassignment_preview(flight_id, crew_id)
        registry._previewed.setdefault(flight_id, set()).add(crew_id)
        registry._verdicts[(flight_id, crew_id)] = verdict
        if verdict["legal"]:
            registry._legal_previews.add((flight_id, crew_id))
        store.note(
            "agent.preview",
            operator,
            f"{flight_id} <- {crew_id} ({verdict['crew_name']}): "
            f"{'LEGAL' if verdict['legal'] else 'REJECTED ' + ','.join(v['code'] for v in verdict['rule_violations'])}",
        )
        return verdict

    registry.register(
        ToolSpec(
            name="preview_reassignment",
            description=(
                "Validate one proposed crew member against one flight using the FAR117/DGCA "
                "rules engine. Returns legal true/false plus the exact rule violations. This "
                "is the only way to establish that an assignment is permitted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "flight_id": {"type": "string"},
                    "crew_id": {"type": "string", "description": "e.g. IC-507"},
                },
                "required": ["flight_id", "crew_id"],
            },
            handler=preview_reassignment,
        )
    )

    # -- 4. Commit (guarded) ----------------------------------------------
    def commit_reassignment(flight_id: str, crew_id: str, rationale: str = "") -> Dict[str, Any]:
        if (flight_id, crew_id) not in registry._legal_previews:
            raise GuardRejection(
                f"refused: no legal preview on record for {flight_id} <- {crew_id}. "
                "Call preview_reassignment first and only commit a pair the rules engine cleared."
            )
        if any(c["flight_id"] == flight_id for c in registry.commitments):
            raise GuardRejection(f"refused: {flight_id} already has a proposed reassignment this run.")
        verdict = registry._verdicts[(flight_id, crew_id)]
        entry = {
            "flight_id": flight_id,
            "crew_id": crew_id,
            "crew_name": verdict["crew_name"],
            "aircraft_type": verdict["aircraft_type"],
            "ruleset_version": verdict["ruleset_version"],
            "checks": verdict["checks"],
            "rationale": rationale,
        }
        registry.commitments.append(entry)
        store.note(
            "agent.reassignment_proposed",
            operator,
            f"{flight_id} <- {crew_id} ({verdict['crew_name']}) cleared by "
            f"ruleset {verdict['ruleset_version']}. {rationale}",
        )
        return {
            "committed": True,
            "assignment": entry,
            "note": (
                "Added to this run's recovery plan. Publishing still requires the existing "
                "approve -> deploy governance gates; the agent does not deploy."
            ),
        }

    registry.register(
        ToolSpec(
            name="commit_reassignment",
            description=(
                "Add a crew reassignment to the recovery plan. Only accepted if the rules "
                "engine already returned legal=true for this exact pair in this run."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "flight_id": {"type": "string"},
                    "crew_id": {"type": "string"},
                    "rationale": {
                        "type": "string",
                        "description": "Why this candidate over the alternatives.",
                    },
                },
                "required": ["flight_id", "crew_id"],
            },
            handler=commit_reassignment,
        )
    )

    # -- 5. Escalate (guarded) --------------------------------------------
    def escalate_to_tier3(flight_id: str, reason: str) -> Dict[str, Any]:
        flight = flight_record(flight_id)
        if not flight:
            raise WorkflowError(404, "flight_not_found", f"Unknown flight {flight_id}")
        # Crew already committed to another flight in this run are genuinely
        # unavailable, so they do not block escalation.
        committed_elsewhere = {c["crew_id"] for c in registry.commitments}
        candidates = {c["id"] for c in type_rated_candidates(flight_id)} - committed_elsewhere
        evaluated = registry.previewed_crew(flight_id)
        remaining = candidates - evaluated
        if remaining:
            raise GuardRejection(
                f"refused: {len(remaining)} type-rated candidate(s) for {flight_id} have not "
                f"been evaluated yet ({', '.join(sorted(remaining))}). Preview them before escalating."
            )
        if registry.has_legal_option(flight_id):
            raise GuardRejection(
                f"refused: a legal option exists for {flight_id}. Commit it instead of escalating."
            )
        blockers = []
        for crew_id in sorted(evaluated):
            verdict = registry._verdicts[(flight_id, crew_id)]
            blockers.append(
                {
                    "crew_id": crew_id,
                    "crew_name": verdict["crew_name"],
                    "violations": [v["code"] for v in verdict["rule_violations"]],
                    "detail": "; ".join(v.get("message", "") for v in verdict["rule_violations"]),
                }
            )
        entry = {
            "flight_id": flight_id,
            "passengers": flight["passengers"],
            "reason": reason,
            "candidates_evaluated": len(evaluated),
            "blockers": blockers,
        }
        registry.escalations.append(entry)
        store.note(
            "agent.escalated_tier3",
            operator,
            f"{flight_id}: no legal option across {len(evaluated)} type-rated candidate(s). {reason}",
        )
        return {"escalated": True, "case": entry}

    registry.register(
        ToolSpec(
            name="escalate_to_tier3",
            description=(
                "Hand a flight to the human scheduler queue. Only accepted once every "
                "type-rated candidate has been evaluated and none was legal."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "flight_id": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "description": "Justification a duty manager can act on.",
                    },
                },
                "required": ["flight_id", "reason"],
            },
            handler=escalate_to_tier3,
        )
    )

    # -- 6. Telemetry ------------------------------------------------------
    registry.register(
        ToolSpec(
            name="get_solver_tiers",
            description=(
                "Run the Tier 1 (greedy/LNS) and Tier 2 (column generation) solvers and return "
                "their coverage and objective telemetry."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=store.solver_tiers,
        )
    )

    return registry
