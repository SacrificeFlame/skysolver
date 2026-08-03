"""The recovery agent loop: perceive -> plan -> act -> observe -> re-plan -> escalate.

The agent proposes a crew recovery plan for the open disruption. It does not
deploy anything: a committed reassignment enters the run's plan and the audit
trail, and publishing it still goes through the existing
scheduler -> duty-manager -> deployment-controller gates. That separation is
deliberate — the agent is fast, the governance is what makes it safe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agents.planner import Decision, DeterministicPlanner, Planner
from agents.tools import ToolRegistry, ToolResult, build_registry, flight_record
from agents.trace import AgentStep, DecisionTrace


class WorldState:
    """The agent's working memory for one run.

    Reads through to the tool registry rather than keeping a second copy of the
    truth, so a planner cannot reason about a legality verdict the registry has
    not actually recorded.
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.perceived = False
        self.open_cases: List[dict] = []
        self.listed_flights: set[str] = set()
        self.picture: Dict[str, Any] = {}

    # -- perception --------------------------------------------------------
    def observe_picture(self, data: Dict[str, Any]) -> None:
        self.picture = data
        self.open_cases = data.get("open_crew_cases", [])
        self.perceived = True

    def mark_listed(self, flight_id: str) -> None:
        self.listed_flights.add(flight_id)

    # -- derived views -----------------------------------------------------
    def is_settled(self, flight_id: str) -> bool:
        return any(c["flight_id"] == flight_id for c in self.registry.commitments) or any(
            e["flight_id"] == flight_id for e in self.registry.escalations
        )

    def evaluated(self, flight_id: str) -> set:
        return self.registry.previewed_crew(flight_id)

    def assigned_crew_ids(self) -> set:
        return {c["crew_id"] for c in self.registry.commitments}

    def legal_option(self, flight_id: str) -> Optional[Tuple[str, dict]]:
        for crew_id in sorted(self.evaluated(flight_id)):
            verdict = self.registry.verdict(flight_id, crew_id)
            if verdict and verdict["legal"] and crew_id not in self.assigned_crew_ids():
                return crew_id, verdict
        return None

    def rejections(self, flight_id: str) -> List[dict]:
        out = []
        for crew_id in sorted(self.evaluated(flight_id)):
            verdict = self.registry.verdict(flight_id, crew_id)
            if not verdict or verdict["legal"]:
                continue
            out.append(
                {
                    "crew_id": crew_id,
                    "crew_name": verdict["crew_name"],
                    "violations": [v["code"] for v in verdict["rule_violations"]],
                    "messages": [v["message"] for v in verdict["rule_violations"]],
                }
            )
        return out

    def flight_origin(self, flight_id: str) -> str:
        flight = flight_record(flight_id)
        return flight["origin"] if flight else ""


@dataclass
class AgentResult:
    trace: DecisionTrace
    resolved: List[dict] = field(default_factory=list)
    escalated: List[dict] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    stopped_because: str = "complete"
    notes: List[str] = field(default_factory=list)
    handover: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planner": self.trace.planner,
            "notes": self.notes,
            "handover": self.handover,
            "summary": {
                "resolved": len(self.resolved),
                "escalated": len(self.escalated),
                "unresolved": len(self.unresolved),
                "tool_calls": self.trace.tool_calls,
                "elapsed_s": round(self.elapsed_s, 3),
                "stopped_because": self.stopped_because,
            },
            "resolved": self.resolved,
            "escalated": self.escalated,
            "unresolved": self.unresolved,
            "trace": self.trace.to_dict(),
        }


class RecoveryAgent:
    """Runs a planner against the guarded tool surface until the board is clear."""

    def __init__(
        self,
        store,
        planner: Optional[Planner] = None,
        operator: str = "recovery-agent",
        max_steps: int = 40,
    ):
        self._store = store
        self._planner: Planner = planner or DeterministicPlanner()
        self._operator = operator
        self._max_steps = max_steps

    def run(self) -> AgentResult:
        started = time.perf_counter()
        registry = build_registry(self._store, operator=self._operator)
        state = WorldState(registry)
        trace = DecisionTrace(planner=self._planner.name)
        stopped = "complete"

        self._store.note(
            "agent.run_started",
            self._operator,
            f"Recovery agent started with the {self._planner.name} planner.",
        )

        last_failure: Optional[str] = None
        for _ in range(self._max_steps):
            decision = self._planner.propose(state)
            if decision is None:
                break
            signature = f"{decision.tool}:{sorted(decision.args.items())}"
            result, duration_ms = self._invoke(registry, decision)
            self._observe(state, decision, result)
            # Planners that keep their own conversation state (the LLM planner)
            # need the tool result fed back before the next proposal.
            observer = getattr(self._planner, "observe", None)
            if callable(observer):
                observer(decision, result)
            trace.add(
                AgentStep(
                    index=trace.next_index(),
                    phase=decision.phase,
                    tool=decision.tool,
                    tool_input=dict(decision.args),
                    rationale=decision.rationale,
                    outcome=self._summarise(decision, result),
                    observation=result.to_dict(),
                    ok=result.ok,
                    duration_ms=duration_ms,
                )
            )
            if result.ok:
                last_failure = None
                continue
            if self._is_fatal(state, decision, result):
                stopped = f"blocked: {result.error}"
                break
            # A guard rejection is feedback the planner is expected to route
            # around. Repeating the identical rejected call means it cannot.
            if signature == last_failure:
                stopped = f"planner stalled on {decision.tool}: {result.error}"
                break
            last_failure = signature
        else:
            stopped = f"step limit ({self._max_steps}) reached"

        trace.close()
        unresolved = [
            c["flight_id"] for c in state.open_cases if not state.is_settled(c["flight_id"])
        ]
        result = AgentResult(
            trace=trace,
            resolved=list(registry.commitments),
            escalated=list(registry.escalations),
            unresolved=unresolved,
            elapsed_s=time.perf_counter() - started,
            stopped_because=stopped,
            notes=list(getattr(self._planner, "events", [])),
            handover=getattr(self._planner, "handover", ""),
        )
        # The planner may have degraded to a fallback mid-run; report what ran.
        trace.planner = getattr(self._planner, "name", trace.planner)
        self._store.note(
            "agent.run_finished",
            self._operator,
            f"{len(result.resolved)} reassignment(s) proposed, {len(result.escalated)} escalated, "
            f"{len(unresolved)} unresolved across {trace.tool_calls} tool calls.",
        )
        return result

    # -- loop internals ----------------------------------------------------
    @staticmethod
    def _invoke(registry: ToolRegistry, decision: Decision) -> Tuple[ToolResult, int]:
        start = time.perf_counter()
        result = registry.run(decision.tool, **decision.args)
        return result, int((time.perf_counter() - start) * 1000)

    @staticmethod
    def _observe(state: WorldState, decision: Decision, result: ToolResult) -> None:
        if not result.ok:
            return
        if decision.tool == "get_operational_picture":
            state.observe_picture(result.data)
        elif decision.tool == "list_candidate_crew":
            state.mark_listed(result.data["flight_id"])

    @staticmethod
    def _is_fatal(state: WorldState, decision: Decision, result: ToolResult) -> bool:
        """A guard rejection is feedback, not a crash — unless we cannot perceive."""
        return decision.tool == "get_operational_picture"

    @staticmethod
    def _summarise(decision: Decision, result: ToolResult) -> str:
        if not result.ok:
            return f"rejected - {result.error}"
        data = result.data
        if decision.tool == "get_operational_picture":
            cases = data.get("open_crew_cases", [])
            if not cases:
                return "No open crew legality cases."
            detail = ", ".join(
                f"{c['flight_id']} ({c['passengers']} pax, {c['type_rated_candidates']} rated candidates)"
                for c in cases
            )
            return f"{len(cases)} open crew case(s): {detail}"
        if decision.tool == "list_candidate_crew":
            names = ", ".join(c["crew_id"] for c in data["candidates"])
            return f"{data['candidate_count']} {data['required_qualification']}-rated candidate(s): {names or 'none'}"
        if decision.tool == "preview_reassignment":
            if data["legal"]:
                return f"LEGAL - {data['crew_name']} cleared by ruleset {data['ruleset_version']}"
            codes = ", ".join(v["code"] for v in data["rule_violations"])
            reasons = "; ".join(v["message"] for v in data["rule_violations"])
            return f"REJECTED [{codes}] - {reasons}"
        if decision.tool == "commit_reassignment":
            a = data["assignment"]
            return f"Added to plan: {a['flight_id']} <- {a['crew_id']} {a['crew_name']}"
        if decision.tool == "escalate_to_tier3":
            case = data["case"]
            return (
                f"Escalated to Tier 3 after {case['candidates_evaluated']} candidate(s); "
                f"{case['passengers']} passengers await a scheduler decision"
            )
        if decision.tool == "get_solver_tiers":
            tiers = ", ".join(f"{t['id']}={t['status']}" for t in data["tiers"])
            return f"Solver telemetry: {tiers}"
        return "ok"
