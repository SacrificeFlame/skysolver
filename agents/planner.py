"""Planners decide *what to try next*. They never decide what is allowed.

Two implementations share one interface:

* ``DeterministicPlanner`` — a scarcity-aware constraint heuristic. No network,
  no API key, no variance. This is what runs when the LLM is unavailable,
  rate-limited or misconfigured, so a live demonstration can never be broken by
  a dead credential.
* the LLM planner (Phase 2) — drops into the same ``Planner`` protocol and gets
  the same tool surface from ``agents.tools.build_registry``.

Whichever planner is driving, ``agents.tools`` enforces the invariants: nothing
is committed without a legal verdict from the rules engine, and nothing is
escalated until every type-rated candidate has genuinely been evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol

from agents.tools import type_rated_candidates

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agents.recovery_agent import WorldState


@dataclass
class Decision:
    """One proposed action, with the reasoning that produced it."""

    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    phase: str = "act"


class Planner(Protocol):
    name: str

    def propose(self, state: "WorldState") -> Optional[Decision]:
        """Return the next action, or None when there is nothing left to do."""
        ...


# --------------------------------------------------------------------------
# Deterministic planner
# --------------------------------------------------------------------------

class DeterministicPlanner:
    """Constraint-driven recovery policy.

    Case ordering uses minimum-remaining-values: work the *most constrained*
    flight first, because a flight with two possible crew is the one most likely
    to need a human, and finding that out early leaves the roomier cases
    untouched. Ties break toward the larger passenger exposure.

    Candidate ordering is scarcity-aware: a crew member who holds a rare type
    rating that another unresolved flight depends on is ranked down, so the
    agent does not spend a scarce B787 captain on a flight that any of eight
    A321 captains could take.
    """

    name = "deterministic"

    def propose(self, state: "WorldState") -> Optional[Decision]:
        if not state.perceived:
            return Decision(
                tool="get_operational_picture",
                rationale="Establish the current disruption state before proposing anything.",
                phase="perceive",
            )

        case = self._select_case(state)
        if case is None:
            return None

        flight_id = case["flight_id"]

        # A cleared option already exists — take it.
        legal = state.legal_option(flight_id)
        if legal:
            crew_id, verdict = legal
            return Decision(
                tool="commit_reassignment",
                args={
                    "flight_id": flight_id,
                    "crew_id": crew_id,
                    "rationale": self._commit_rationale(state, case, crew_id, verdict),
                },
                rationale=(
                    f"Rules engine {verdict['ruleset_version']} cleared {crew_id} for {flight_id}; "
                    "it is the highest-ranked legal option found."
                ),
                phase="act",
            )

        remaining = self._remaining_candidates(state, flight_id)

        # Every type-rated candidate has been rejected by the engine.
        if not remaining:
            return Decision(
                tool="escalate_to_tier3",
                args={"flight_id": flight_id, "reason": self._escalation_reason(state, case)},
                rationale=(
                    f"All {len(state.evaluated(flight_id))} type-rated candidate(s) for {flight_id} "
                    "were rejected by the rules engine. Automation cannot resolve this legally."
                ),
                phase="escalate",
            )

        # Show the shortlist once per flight so the trace explains the search space.
        if flight_id not in state.listed_flights:
            return Decision(
                tool="list_candidate_crew",
                args={"flight_id": flight_id},
                rationale=(
                    f"{flight_id} needs a {case['required_qualification']}-rated replacement for "
                    f"{case['incumbent_crew_id']} (duty remaining {case['incumbent_duty_remaining']}). "
                    "Enumerate who is actually available."
                ),
                phase="plan",
            )

        ranked = self._rank(state, case, remaining)
        pick = ranked[0]
        return Decision(
            tool="preview_reassignment",
            args={"flight_id": flight_id, "crew_id": pick["crew_id"]},
            rationale=self._pick_rationale(case, pick, ranked[1:]),
            phase="act",
        )

    # -- case selection ----------------------------------------------------
    def _select_case(self, state: "WorldState") -> Optional[dict]:
        open_cases = [c for c in state.open_cases if not state.is_settled(c["flight_id"])]
        if not open_cases:
            return None
        return min(
            open_cases,
            key=lambda c: (
                len(self._remaining_candidates(state, c["flight_id"])),
                -c["passengers"],
                c["flight_id"],
            ),
        )

    @staticmethod
    def _remaining_candidates(state: "WorldState", flight_id: str) -> List[dict]:
        evaluated = state.evaluated(flight_id)
        taken = state.assigned_crew_ids()
        return [
            c
            for c in type_rated_candidates(flight_id)
            if c["id"] not in evaluated and c["id"] not in taken
        ]

    # -- candidate ranking -------------------------------------------------
    def _scarcity_cost(self, state: "WorldState", crew: dict, flight_id: str) -> float:
        """How badly other unresolved flights need this crew member's ratings.

        Each competing flight contributes 1 / (its candidate count), so being
        one of two options for another flight costs far more than being one of
        eight.
        """
        cost = 0.0
        for other in state.open_cases:
            other_id = other["flight_id"]
            if other_id == flight_id or state.is_settled(other_id):
                continue
            pool = self._remaining_candidates(state, other_id)
            if any(c["id"] == crew["id"] for c in pool) and pool:
                cost += 1.0 / len(pool)
        return cost

    def _rank(self, state: "WorldState", case: dict, candidates: List[dict]) -> List[dict]:
        origin = state.flight_origin(case["flight_id"])
        ranked = []
        for crew in candidates:
            ranked.append(
                {
                    "crew_id": crew["id"],
                    "name": crew["name"],
                    "base": crew["base"],
                    "rest_hours": crew["rest_hours"],
                    "seniority": crew["seniority"],
                    "qualifications": list(crew["qualifications"]),
                    "positioned": crew["base"] == origin,
                    "scarcity_cost": round(self._scarcity_cost(state, crew, case["flight_id"]), 3),
                }
            )
        ranked.sort(
            key=lambda c: (
                c["scarcity_cost"],          # preserve crew other flights depend on
                0 if c["positioned"] else 1,  # avoid a positioning violation
                -c["rest_hours"],             # most rested first
                -c["seniority"],
                c["crew_id"],
            )
        )
        return ranked

    # -- rationale text ----------------------------------------------------
    @staticmethod
    def _pick_rationale(case: dict, pick: dict, rest: List[dict]) -> str:
        parts = [
            f"{pick['crew_id']} {pick['name']} - rated {'/'.join(pick['qualifications'])}, "
            f"based {pick['base']} ({case['flight_id']} departs {case.get('route', '?').split('-')[0]}), "
            f"{pick['rest_hours']}h rest"
        ]
        deprioritised = next((c for c in rest if c["scarcity_cost"] > pick["scarcity_cost"]), None)
        if deprioritised:
            parts.append(
                f"ranked above {deprioritised['crew_id']} {deprioritised['name']}, who is held back "
                f"because a scarcer rating ({'/'.join(deprioritised['qualifications'])}) is needed elsewhere"
            )
        parts.append("legality still to be decided by the rules engine")
        return "; ".join(parts) + "."

    @staticmethod
    def _commit_rationale(state: "WorldState", case: dict, crew_id: str, verdict: dict) -> str:
        checks = verdict["checks"]
        passed = [k for k, v in checks.items() if v]
        rejected = state.rejections(case["flight_id"])
        text = (
            f"{verdict['crew_name']} ({crew_id}) cleared for {case['flight_id']} "
            f"[{', '.join(passed)}] under ruleset {verdict['ruleset_version']}. "
            f"Protects {case['passengers']} passengers and {case['connections']} onward connections."
        )
        if rejected:
            text += " Earlier candidates rejected: " + "; ".join(
                f"{r['crew_id']} ({','.join(r['violations'])})" for r in rejected
            ) + "."
        return text

    @staticmethod
    def _escalation_reason(state: "WorldState", case: dict) -> str:
        rejected = state.rejections(case["flight_id"])
        detail = "; ".join(
            f"{r['crew_id']} {r['crew_name']} - {', '.join(r['messages'])}" for r in rejected
        )
        return (
            f"No legal {case['required_qualification']} option for {case['flight_id']} "
            f"({case['passengers']} passengers, {case['connections']} connections). "
            f"Evaluated {len(rejected)} type-rated candidate(s): {detail}. "
            "Requires a duty-manager decision the automation is not permitted to make on its own - "
            "positioning a rated captain to the origin, re-timing the departure to clear the rest "
            "shortfall, or accepting a cancellation."
        )
