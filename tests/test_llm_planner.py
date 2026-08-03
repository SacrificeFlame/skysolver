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


def test_parallel_tool_calls_are_disabled(store, monkeypatch):
    script = [SimpleNamespace(content="done", tool_calls=None)]
    planner = _planner(script, monkeypatch)
    RecoveryAgent(store, planner=planner).run()
    assert planner._client.chat.completions.requests[0]["parallel_tool_calls"] is False


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
    script = [RateLimitError("429 quota spent")] * 5
    planner = OpenAIPlanner(
        provider="gemini",
        client=FakeClient(script),
        min_interval_s=0,
        backoff_s=0,
        rate_limit_retries=2,
    )
    result = RecoveryAgent(store, planner=planner).run()

    assert len(result.notes) == 1
    # Three attempts made (initial + 2 retries) before giving up.
    assert len(planner._client.chat.completions.requests) == 3
    assert result.unresolved == []  # deterministic planner still finished the job


def test_non_rate_limit_errors_are_not_retried(store):
    script = [FakeQuotaError("400 bad request"), FakeQuotaError("400 bad request")]
    planner = OpenAIPlanner(
        provider="gemini", client=FakeClient(script), min_interval_s=0, backoff_s=0
    )
    RecoveryAgent(store, planner=planner).run()
    assert len(planner._client.chat.completions.requests) == 1


def test_throttle_paces_calls_without_delaying_the_first(store, monkeypatch):
    sleeps = []
    monkeypatch.setattr("agents.llm_planner.time.sleep", sleeps.append)
    script = [
        SimpleNamespace(content="one", tool_calls=[_tool_call("c1", "get_operational_picture", {})]),
        SimpleNamespace(content="two", tool_calls=[
            _tool_call("c2", "list_candidate_crew", {"flight_id": "AI807"})]),
        SimpleNamespace(content="done", tool_calls=None),
    ]
    planner = OpenAIPlanner(provider="gemini", client=FakeClient(script), min_interval_s=5.0)
    RecoveryAgent(store, planner=planner).run()

    assert sleeps, "expected the throttle to pace subsequent calls"
    assert all(0 < s <= 5.0 for s in sleeps)


def test_gemini_is_throttled_by_default_and_openai_is_not():
    gemini = OpenAIPlanner(provider="gemini", client=FakeClient([]))
    openai = OpenAIPlanner(provider="openai", client=FakeClient([]))
    assert gemini._min_interval_s > 0
    assert openai._min_interval_s == 0
