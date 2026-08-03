"""LLM planner: tool-schema wiring, conversation handling, and degradation.

These tests run without network access. A fake client stands in for OpenAI so
the loop, the message plumbing and — most importantly — the failure path are
verified deterministically in CI.
"""

import json
from types import SimpleNamespace

import pytest

from agents.llm_planner import PROVIDERS, OpenAIPlanner, _as_openai_functions, _compact
from agents.recovery_agent import RecoveryAgent
from agents.tools import build_registry
from deployment.recovery_api import RecoveryStore


@pytest.fixture()
def store():
    return RecoveryStore()


# --------------------------------------------------------------------------
# Fake OpenAI client
# --------------------------------------------------------------------------

def _tool_call(call_id, name, args):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


class FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self._script:
            message = SimpleNamespace(content="All flights settled.", tool_calls=None)
        else:
            message = self._script.pop(0)
            if isinstance(message, Exception):
                raise message
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, script):
        self.chat = SimpleNamespace(completions=FakeCompletions(script))


def _planner(script, monkeypatch, **kwargs):
    """Inject a fake transport — no OpenAI client, no key, no network."""
    return OpenAIPlanner(model="gpt-4o", client=FakeClient(script), **kwargs)


# --------------------------------------------------------------------------
# Tool schema translation
# --------------------------------------------------------------------------

def test_openai_functions_mirror_the_registry_schemas(store):
    registry = build_registry(store)
    functions = _as_openai_functions(registry.anthropic_tools())

    assert {f["name"] for f in functions} == set(registry.names())
    for fn in functions:
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_preview_output_is_compacted_but_keeps_the_verdict(store):
    registry = build_registry(store)
    result = registry.run("preview_reassignment", flight_id="AI807", crew_id="IC-507")
    compact = _compact(result.to_dict())

    assert compact["data"]["legal"] is False
    assert compact["data"]["rule_violations"] == [
        {"code": "MIN_REST", "message": compact["data"]["rule_violations"][0]["message"]}
    ]
    # Provenance and ruleset noise are dropped before re-entering the context window.
    assert "provenance" not in compact["data"]


# --------------------------------------------------------------------------
# Conversation plumbing
# --------------------------------------------------------------------------

def test_planner_drives_the_loop_and_feeds_results_back(store, monkeypatch):
    script = [
        SimpleNamespace(content="Read the picture.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        SimpleNamespace(content="Check IC-318.", tool_calls=[
            _tool_call("c2", "preview_reassignment", {"flight_id": "AI421", "crew_id": "IC-318"})]),
        SimpleNamespace(content="Commit it.", tool_calls=[
            _tool_call("c3", "commit_reassignment", {"flight_id": "AI421", "crew_id": "IC-318"})]),
        SimpleNamespace(content="AI421 resolved; AI807 needs you.", tool_calls=None),
    ]
    planner = _planner(script, monkeypatch)
    result = RecoveryAgent(store, planner=planner).run()

    assert [r["flight_id"] for r in result.resolved] == ["AI421"]
    assert result.handover == "AI421 resolved; AI807 needs you."
    assert result.notes == []  # never degraded

    # Every assistant tool_call was answered with a matching tool message.
    messages = planner._messages
    call_ids = {c["id"] for m in messages if m.get("tool_calls") for c in m["tool_calls"]}
    reply_ids = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    assert call_ids == reply_ids


def test_model_rationale_is_captured_in_the_trace(store, monkeypatch):
    script = [
        SimpleNamespace(content="Establishing the picture first.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        SimpleNamespace(content="done", tool_calls=None),
    ]
    result = RecoveryAgent(store, planner=_planner(script, monkeypatch)).run()
    assert result.trace.steps[0].rationale == "Establishing the picture first."


def test_batched_tool_calls_are_allowed(store, monkeypatch):
    script = [SimpleNamespace(content="done", tool_calls=None)]
    planner = _planner(script, monkeypatch)
    RecoveryAgent(store, planner=planner).run()
    assert planner._client.chat.completions.requests[0]["parallel_tool_calls"] is True


def test_a_batched_turn_costs_one_round_trip_not_one_per_call(store, monkeypatch):
    """The wall-clock cost of a run is API round trips, not tool calls."""
    script = [
        SimpleNamespace(content="Evaluate both B787 candidates at once.", tool_calls=[
            _tool_call("c1", "preview_reassignment", {"flight_id": "AI807", "crew_id": "IC-507"}),
            _tool_call("c2", "preview_reassignment", {"flight_id": "AI807", "crew_id": "IC-560"}),
            _tool_call("c3", "list_candidate_crew", {"flight_id": "AI421"}),
        ]),
        SimpleNamespace(content="done", tool_calls=None),
    ]
    planner = _planner(script, monkeypatch)
    result = RecoveryAgent(store, planner=planner).run()

    # Three tools executed, two API calls: the batch plus the closing turn.
    assert len(result.trace.steps) == 3
    assert len(planner._client.chat.completions.requests) == 2

    # Each still ran through the registry and produced a real verdict.
    codes = {c for s in result.trace.steps if s.tool == "preview_reassignment"
             for c in [v["code"] for v in s.observation["data"]["rule_violations"]]}
    assert codes == {"MIN_REST", "CREW_POSITION"}

    # Every batched call was answered individually in the transcript.
    call_ids = {c["id"] for m in planner._messages if m.get("tool_calls") for c in m["tool_calls"]}
    reply_ids = {m["tool_call_id"] for m in planner._messages if m["role"] == "tool"}
    assert call_ids == reply_ids == {"c1", "c2", "c3"}


def test_guards_still_apply_inside_a_single_batch(store, monkeypatch):
    """Batching must not let a commit skip the verdict it depends on."""
    script = [
        SimpleNamespace(content="Preview then commit together.", tool_calls=[
            # IC-507 fails MIN_REST, so the commit batched behind it must be refused.
            _tool_call("c1", "preview_reassignment", {"flight_id": "AI807", "crew_id": "IC-507"}),
            _tool_call("c2", "commit_reassignment", {"flight_id": "AI807", "crew_id": "IC-507"}),
        ]),
        SimpleNamespace(content="Understood.", tool_calls=None),
    ]
    result = RecoveryAgent(store, planner=_planner(script, monkeypatch)).run()

    assert result.resolved == []
    commit = next(s for s in result.trace.steps if s.tool == "commit_reassignment")
    assert commit.ok is False
    assert "no legal preview on record" in commit.observation["error"]


# --------------------------------------------------------------------------
# Safety: the model cannot talk its way past the rules engine
# --------------------------------------------------------------------------

def test_model_cannot_commit_a_crew_the_engine_rejected(store, monkeypatch):
    script = [
        SimpleNamespace(content="Picture.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        # IC-507 fails MIN_REST for AI807; commit without previewing.
        SimpleNamespace(content="IC-507 is clearly fine.", tool_calls=[
            _tool_call("c2", "commit_reassignment", {"flight_id": "AI807", "crew_id": "IC-507"})]),
        SimpleNamespace(content="Understood.", tool_calls=None),
    ]
    result = RecoveryAgent(store, planner=_planner(script, monkeypatch)).run()

    assert result.resolved == []
    refusal = next(s for s in result.trace.steps if s.tool == "commit_reassignment")
    assert refusal.ok is False
    assert "no legal preview on record" in refusal.observation["error"]


def test_model_cannot_escalate_a_flight_it_never_evaluated(store, monkeypatch):
    script = [
        SimpleNamespace(content="Picture.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        SimpleNamespace(content="This looks hopeless.", tool_calls=[
            _tool_call("c2", "escalate_to_tier3", {"flight_id": "AI421", "reason": "hard"})]),
        SimpleNamespace(content="Understood.", tool_calls=None),
    ]
    result = RecoveryAgent(store, planner=_planner(script, monkeypatch)).run()

    assert result.escalated == []
    refusal = next(s for s in result.trace.steps if s.tool == "escalate_to_tier3")
    assert refusal.ok is False


# --------------------------------------------------------------------------
# Degradation: a dead credential must not break a demonstration
# --------------------------------------------------------------------------

class FakeQuotaError(Exception):
    pass


def test_planner_degrades_to_deterministic_when_the_api_fails(store, monkeypatch):
    script = [FakeQuotaError("Error code: 429 - insufficient_quota")]
    planner = _planner(script, monkeypatch)
    result = RecoveryAgent(store, planner=planner).run()

    # Same plan the deterministic planner produces on its own.
    assert {r["flight_id"] for r in result.resolved} == {"AI421", "UK945"}
    assert {e["flight_id"] for e in result.escalated} == {"AI807"}
    assert result.unresolved == []

    assert len(result.notes) == 1
    assert "Switched to the deterministic planner" in result.notes[0]
    assert "deterministic" in result.trace.planner


def test_degradation_mid_run_still_completes_the_plan(store, monkeypatch):
    script = [
        SimpleNamespace(content="Picture.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        FakeQuotaError("Error code: 429 - insufficient_quota"),
    ]
    result = RecoveryAgent(store, planner=_planner(script, monkeypatch)).run()

    assert result.unresolved == []
    assert len(result.resolved) == 2
    assert len(result.escalated) == 1


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAIPlanner()


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

def test_gemini_provider_names_the_right_key_and_console(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError) as exc:
        OpenAIPlanner(provider="gemini")
    message = str(exc.value)
    assert "GEMINI_API_KEY or GOOGLE_API_KEY" in message
    assert "aistudio.google.com" in message


def test_gemini_provider_is_configured_for_the_compatible_endpoint():
    config = PROVIDERS["gemini"]
    assert config["base_url"].endswith("/v1beta/openai/")
    assert config["default_model"].startswith("gemini")


def test_provider_appears_in_the_planner_name(store, monkeypatch):
    script = [SimpleNamespace(content="done", tool_calls=None)]
    planner = OpenAIPlanner(provider="gemini", client=FakeClient(script))
    assert planner.name.startswith("gemini:")
    result = RecoveryAgent(store, planner=planner).run()
    assert result.trace.planner.startswith("gemini:")


def test_gemini_degrades_like_any_other_provider(store):
    planner = OpenAIPlanner(
        provider="gemini", client=FakeClient([FakeQuotaError("429 quota")])
    )
    result = RecoveryAgent(store, planner=planner).run()
    assert {r["flight_id"] for r in result.resolved} == {"AI421", "UK945"}
    assert "gemini" in result.trace.planner and "deterministic" in result.trace.planner


@pytest.mark.parametrize(
    "exc,expected",
    [
        (type("RateLimitError", (Exception,), {})("429 exceeded your quota"), "quota is exhausted"),
        (type("RateLimitError", (Exception,), {})("429 too many requests"), "rate limiting"),
        (type("E", (Exception,), {"status_code": 401})(), "rejected the API key"),
        (type("E", (Exception,), {"status_code": 404})(), "not available to this account"),
        (type("E", (Exception,), {"status_code": 503})(), "server error"),
        (ValueError("boom"), "could not be reached"),
    ],
)
def test_failures_are_explained_without_leaking_a_stack_trace(exc, expected):
    from agents.llm_planner import _explain

    message = _explain(exc)
    assert expected in message
    # An operator reads this in the UI; it must not be a raw provider dump.
    assert "Traceback" not in message and len(message) < 120


def test_unknown_provider_is_rejected():
    with pytest.raises(RuntimeError, match="Unknown provider"):
        OpenAIPlanner(provider="nope")


# --------------------------------------------------------------------------
# Rate limiting: transient 429s are retried, exhausted quota degrades
# --------------------------------------------------------------------------

class RateLimitError(Exception):
    """Matches the provider SDK class name that _is_rate_limit looks for."""


def test_a_transient_rate_limit_is_retried_not_fatal(store):
    script = [
        RateLimitError("429 too fast"),
        SimpleNamespace(content="Recovered.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        SimpleNamespace(content="done", tool_calls=None),
    ]
    planner = OpenAIPlanner(
        provider="gemini", client=FakeClient(script), min_interval_s=0, backoff_s=0
    )
    result = RecoveryAgent(store, planner=planner).run()

    assert result.notes == []  # retried, never degraded
    assert result.trace.steps[0].tool == "get_operational_picture"


def test_a_persistent_rate_limit_degrades_after_the_retries(store):
    # Enough failures that every model in the chain is exhausted.
    script = [RateLimitError("429 quota spent")] * 20
    planner = OpenAIPlanner(
        provider="gemini",
        client=FakeClient(script),
        min_interval_s=0,
        backoff_s=0,
        rate_limit_retries=2,
    )
    result = RecoveryAgent(store, planner=planner).run()

    # Three attempts per model (initial + 2 retries) across the whole chain,
    # then it gives up. The chain length is configuration, so assert the shape.
    attempts = planner._client.chat.completions.requests
    assert len(attempts) == 3 * (1 + len(PROVIDERS["gemini"]["fallback_models"]))
    assert {a["model"] for a in attempts} == {
        "gemini-flash-latest", *PROVIDERS["gemini"]["fallback_models"]
    }
    assert any("deterministic planner" in n for n in result.notes)
    assert result.unresolved == []  # deterministic planner still finished the job


def test_non_rate_limit_errors_are_not_retried(store):
    script = [FakeQuotaError("400 bad request"), FakeQuotaError("400 bad request")]
    planner = OpenAIPlanner(
        provider="gemini", client=FakeClient(script), min_interval_s=0, backoff_s=0
    )
    RecoveryAgent(store, planner=planner).run()
    assert len(planner._client.chat.completions.requests) == 1


def test_calls_are_not_paced_until_the_provider_pushes_back(store,monkeypatch):
    """An unconstrained run must not pay a throttle it has no evidence it needs."""
    sleeps=[]
    monkeypatch.setattr("agents.llm_planner.time.sleep",sleeps.append)
    script=[
        SimpleNamespace(content="one",tool_calls=[_tool_call("c1","get_operational_picture",{})]),
        SimpleNamespace(content="two",tool_calls=[
            _tool_call("c2","list_candidate_crew",{"flight_id":"AI807"})]),
        SimpleNamespace(content="done",tool_calls=None),
    ]
    planner=OpenAIPlanner(provider="gemini",client=FakeClient(script))
    RecoveryAgent(store,planner=planner).run()

    assert sleeps==[], "a healthy run should never wait"
    assert planner._min_interval_s==0


def test_pacing_engages_after_a_rate_limit_and_stays_on(store,monkeypatch):
    sleeps=[]
    monkeypatch.setattr("agents.llm_planner.time.sleep",sleeps.append)
    script=[
        RateLimitError("429 slow down"),
        SimpleNamespace(content="one",tool_calls=[_tool_call("c1","get_operational_picture",{})]),
        SimpleNamespace(content="two",tool_calls=[
            _tool_call("c2","list_candidate_crew",{"flight_id":"AI807"})]),
        SimpleNamespace(content="done",tool_calls=None),
    ]
    planner=OpenAIPlanner(provider="gemini",client=FakeClient(script),backoff_s=0)
    result=RecoveryAgent(store,planner=planner).run()

    assert planner._min_interval_s==PROVIDERS["gemini"]["min_interval_s"]
    assert any("spaced" in n for n in result.notes)
    # Paced from then on, but never degraded: the retry succeeded.
    assert "deterministic" not in result.trace.planner
    assert any(s>0 for s in sleeps)


def test_gemini_has_a_pace_to_fall_back_to_and_openai_does_not():
    gemini = OpenAIPlanner(provider="gemini", client=FakeClient([]))
    openai = OpenAIPlanner(provider="openai", client=FakeClient([]))
    # Configured, but not applied until a 429 proves it is needed.
    assert gemini._paced_interval_s > 0
    assert gemini._min_interval_s == 0
    assert openai._paced_interval_s == 0


# --------------------------------------------------------------------------
# Model fallback: quota is charged per model, so step down before giving up
# --------------------------------------------------------------------------

def test_quota_on_the_primary_model_steps_down_before_degrading(store):
    script = [
        RateLimitError("429 exceeded your current quota"),
        RateLimitError("429 exceeded your current quota"),
        RateLimitError("429 exceeded your current quota"),
        SimpleNamespace(content="On the lite model now.", tool_calls=[
            _tool_call("c1", "get_operational_picture", {})]),
        SimpleNamespace(content="done", tool_calls=None),
    ]
    planner = OpenAIPlanner(
        provider="gemini", client=FakeClient(script),
        min_interval_s=0, backoff_s=0, rate_limit_retries=2,
    )
    result = RecoveryAgent(store, planner=planner).run()

    assert planner.model == "gemini-flash-lite-latest"
    assert "continued on gemini-flash-lite-latest" in " ".join(result.notes)
    assert "deterministic" not in result.trace.planner  # never gave up on the LLM
    assert result.trace.steps[0].tool == "get_operational_picture"


def test_quota_on_every_model_finally_degrades(store):
    planner = OpenAIPlanner(
        provider="gemini", client=FakeClient([RateLimitError("429 quota")] * 12),
        min_interval_s=0, backoff_s=0, rate_limit_retries=1,
    )
    result = RecoveryAgent(store, planner=planner).run()

    assert "deterministic" in result.trace.planner
    assert result.unresolved == []  # the plan still completes
    assert any("continued on" in n for n in result.notes)
    assert any("quota is exhausted" in n for n in result.notes)


def test_an_explicit_model_choice_is_not_duplicated_in_the_chain():
    planner = OpenAIPlanner(
        provider="gemini", model="gemini-flash-lite-latest", client=FakeClient([]),
    )
    assert "gemini-flash-lite-latest" not in planner._model_queue


def test_openai_has_no_model_chain_configured():
    planner = OpenAIPlanner(provider="openai", client=FakeClient([]))
    assert planner._model_queue == []


def test_degrade_note_does_not_duplicate_the_callers_reassurance():
    planner = OpenAIPlanner(provider="gemini", client=FakeClient([]))
    planner._degrade("The model provider's quota is exhausted.")
    note = planner.events[0]
    assert note.count("recovery plan") == 0  # the UI says that once, not twice
    assert note.endswith("for the remainder of the run.")
