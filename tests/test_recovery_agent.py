"""Recovery agent: safety invariants and end-to-end behaviour.

The invariant tests matter more than the happy path. They assert that the
guards in ``agents.tools`` hold against a *misbehaving planner* — which is the
threat model once an LLM is driving in Phase 2.
"""

import pytest

from agents.planner import Decision, DeterministicPlanner
from agents.recovery_agent import RecoveryAgent
from agents.tools import build_registry, open_crew_cases, type_rated_candidates
from deployment.recovery_api import RecoveryStore


@pytest.fixture()
def store():
    return RecoveryStore()


# --------------------------------------------------------------------------
# Guards: an illegal plan must be impossible, not merely discouraged
# --------------------------------------------------------------------------

def test_commit_refused_without_a_legal_preview(store):
    registry = build_registry(store)
    result = registry.run("commit_reassignment", flight_id="AI421", crew_id="IC-318")
    assert not result.ok
    assert "no legal preview on record" in result.error


def test_commit_refused_for_a_crew_the_engine_rejected(store):
    registry = build_registry(store)
    preview = registry.run("preview_reassignment", flight_id="AI807", crew_id="IC-507")
    assert preview.ok and preview.data["legal"] is False  # real MIN_REST rejection

    result = registry.run("commit_reassignment", flight_id="AI807", crew_id="IC-507")
    assert not result.ok
    assert registry.commitments == []


def test_commit_accepted_only_after_a_legal_verdict(store):
    registry = build_registry(store)
    preview = registry.run("preview_reassignment", flight_id="AI421", crew_id="IC-318")
    assert preview.ok and preview.data["legal"] is True

    result = registry.run("commit_reassignment", flight_id="AI421", crew_id="IC-318")
    assert result.ok
    assert [c["flight_id"] for c in registry.commitments] == ["AI421"]


def test_escalation_refused_while_candidates_are_unevaluated(store):
    registry = build_registry(store)
    result = registry.run("escalate_to_tier3", flight_id="AI807", reason="looks hard")
    assert not result.ok
    assert "have not been evaluated" in result.error
    assert registry.escalations == []


def test_escalation_refused_when_a_legal_option_exists(store):
    registry = build_registry(store)
    for crew in type_rated_candidates("AI421"):
        registry.run("preview_reassignment", flight_id="AI421", crew_id=crew["id"])
    result = registry.run("escalate_to_tier3", flight_id="AI421", reason="give up")
    assert not result.ok
    assert "a legal option exists" in result.error


def test_escalation_allowed_once_every_candidate_is_rejected(store):
    registry = build_registry(store)
    for crew in type_rated_candidates("AI807"):
        preview = registry.run("preview_reassignment", flight_id="AI807", crew_id=crew["id"])
        assert preview.data["legal"] is False
    result = registry.run("escalate_to_tier3", flight_id="AI807", reason="no legal option")
    assert result.ok
    assert result.data["case"]["candidates_evaluated"] == 2


# --------------------------------------------------------------------------
# End-to-end run
# --------------------------------------------------------------------------

def test_agent_resolves_what_it_can_and_escalates_the_rest(store):
    result = RecoveryAgent(store, planner=DeterministicPlanner()).run()

    assert result.stopped_because == "complete"
    assert result.unresolved == []

    resolved = {r["flight_id"]: r["crew_id"] for r in result.resolved}
    assert set(resolved) == {"AI421", "UK945"}

    # AI807 has no legal B787 option in the roster, so it must reach a human.
    escalated = {e["flight_id"] for e in result.escalated}
    assert escalated == {"AI807"}


def test_escalation_carries_the_real_rule_violations(store):
    result = RecoveryAgent(store, planner=DeterministicPlanner()).run()
    case = next(e for e in result.escalated if e["flight_id"] == "AI807")

    codes = {code for blocker in case["blockers"] for code in blocker["violations"]}
    assert codes == {"MIN_REST", "CREW_POSITION"}
    assert case["candidates_evaluated"] == 2


def test_every_committed_assignment_is_backed_by_a_legality_check(store):
    result = RecoveryAgent(store, planner=DeterministicPlanner()).run()
    for item in result.resolved:
        assert item["checks"]["qualified"] is True
        assert item["checks"]["positioned_at_origin"] is True
        assert item["checks"]["rest_ok"] is True
        assert item["ruleset_version"]


def test_no_crew_member_is_assigned_to_two_flights(store):
    result = RecoveryAgent(store, planner=DeterministicPlanner()).run()
    crew_ids = [r["crew_id"] for r in result.resolved]
    assert len(crew_ids) == len(set(crew_ids))


def test_run_is_deterministic(store):
    first = RecoveryAgent(store, planner=DeterministicPlanner()).run()
    second = RecoveryAgent(RecoveryStore(), planner=DeterministicPlanner()).run()
    assert [r["crew_id"] for r in first.resolved] == [r["crew_id"] for r in second.resolved]
    assert [s.tool for s in first.trace.steps] == [s.tool for s in second.trace.steps]


# --------------------------------------------------------------------------
# Trace and audit
# --------------------------------------------------------------------------

def test_trace_records_reasoning_for_every_step(store):
    result = RecoveryAgent(store, planner=DeterministicPlanner()).run()
    assert result.trace.tool_calls > 0
    for step in result.trace.steps:
        assert step.rationale, f"step {step.index} ({step.tool}) has no rationale"
        assert step.outcome
        assert step.phase in {"perceive", "plan", "act", "observe", "escalate"}


def test_run_is_written_to_the_audit_trail(store):
    RecoveryAgent(store, planner=DeterministicPlanner()).run()
    actions = [entry["action"] for entry in store.audit()]
    assert "agent.run_started" in actions
    assert "agent.run_finished" in actions
    assert "agent.preview" in actions
    assert "agent.reassignment_proposed" in actions
    assert "agent.escalated_tier3" in actions


def test_agent_does_not_mutate_the_shared_roster(store):
    before = [dict(c) for c in open_crew_cases()]
    RecoveryAgent(store, planner=DeterministicPlanner()).run()
    assert open_crew_cases() == before


# --------------------------------------------------------------------------
# Adversarial planner (the Phase 2 threat model)
# --------------------------------------------------------------------------

class RoguePlanner:
    """Stands in for a hallucinating LLM: commits crew it never validated."""

    name = "rogue"

    def __init__(self):
        self._steps = 0

    def propose(self, state):
        self._steps += 1
        if self._steps == 1:
            return Decision(tool="get_operational_picture", rationale="perceive", phase="perceive")
        if self._steps == 2:
            # IC-507 fails MIN_REST for AI807. Claim it anyway.
            return Decision(
                tool="commit_reassignment",
                args={"flight_id": "AI807", "crew_id": "IC-507"},
                rationale="asserting legality without checking",
            )
        return None


def test_a_rogue_planner_cannot_publish_an_illegal_assignment(store):
    result = RecoveryAgent(store, planner=RoguePlanner()).run()
    assert result.resolved == []
    assert any(not step.ok for step in result.trace.steps)
