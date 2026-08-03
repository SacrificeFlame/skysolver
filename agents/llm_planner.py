"""LLM planner: the model chooses the actions, the rules engine keeps the veto.

The planner sees exactly the tool surface built by ``agents.tools.build_registry``
and nothing else. It cannot read the roster directly, cannot assert that an
assignment is legal, and cannot publish anything — every action it names is
executed by the guarded registry, which refuses a commit without a recorded
legal verdict and refuses an escalation while candidates remain unevaluated.

That division is why an LLM is safe here. The model contributes judgement about
*what is worth trying* — which of nine A321 captains to burn on this flight,
when a search is genuinely exhausted, how to justify an escalation to a duty
manager. It contributes nothing to the question of what is permitted.

If the API is unreachable, rate-limited or unfunded, the planner falls back to
``DeterministicPlanner`` mid-run and records that it did so. A live operations
demonstration must never depend on a credential.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agents.planner import Decision, DeterministicPlanner
from agents.tools import ToolResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agents.recovery_agent import WorldState


DEFAULT_MODEL = "gpt-4o"

# Both providers are driven through the OpenAI SDK. Google exposes an
# OpenAI-compatible endpoint for Gemini, so one planner, one set of tool
# schemas and one test suite cover both — the provider is configuration, not a
# second implementation.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "base_url": None,
        "default_model": "gpt-4o",
        "key_env": ("OPENAI_API_KEY",),
        "console": "platform.openai.com",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        # gemini-2.0-flash is quota-limited on the free tier and gemini-2.5-flash
        # is closed to new projects; the rolling alias is the reliable choice.
        "default_model": "gemini-flash-latest",
        # Free-tier quota is per-model. A lighter model has its own, larger
        # allowance, so an exhausted flash quota should step down rather than
        # abandon the LLM planner entirely.
        "fallback_models": ("gemini-flash-lite-latest",),
        "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "console": "aistudio.google.com/apikey",
        # The free tier allows roughly 10 requests/minute. An unthrottled run
        # issues ~30, so pace the calls rather than burn the allowance and
        # degrade halfway through a demonstration.
        # Pacing applied only *after* the provider rate-limits, not up front.
        # Free-tier Gemini allows roughly 10 requests/minute; an unthrottled run
        # issues ~30 and may trip it. Pacing every run pre-emptively cost ~55s of
        # deliberate waiting on runs that would have been fine, so the interval
        # now engages on the first 429 and stays on for the rest of the run.
        "min_interval_s": 5.0,
    },
}

SYSTEM_PROMPT = """\
You are the recovery agent for an airline operations control centre during an \
active disruption. Crew have gone out of legal duty limits and flights are held.

Your job is to decide, flight by flight, which replacement crew is worth \
evaluating, and to recognise when no legal option exists so a human scheduler \
is brought in rather than left waiting.

Rules of engagement:

1. You do not decide what is legal. The FAR117/DGCA rules engine does. The only \
   way to learn whether an assignment is permitted is to call \
   preview_reassignment and read the verdict. Never assert that a crew member is \
   legal, rested, or positioned - ask.
2. Never call commit_reassignment for a pair the engine has not already cleared. \
   The call will be refused, and the refusal is a bug in your reasoning.
3. Never call escalate_to_tier3 until every type-rated candidate for that flight \
   has actually been previewed and rejected. Escalating early wastes a scheduler's \
   attention; escalating late strands passengers.
4. A crew member can only work one flight. Track what you have committed.
5. Work the most constrained flight first - the one with fewest type-rated \
   candidates. If it turns out to need a human, you want to know early.
6. Prefer not to spend a scarce type rating on a flight that many crew could \
   cover. A captain rated on both B787 and A321 is worth more to the B787 flight.

Call exactly one tool per turn. Start with get_operational_picture.

When every flight is either committed or escalated, stop calling tools and reply \
with a short handover note for the duty manager: what you resolved, what you \
escalated, and what decision the human now owns.

Write that note as two or three sentences of plain prose. It is rendered as text \
in an operations console, so do not use markdown - no headings, asterisks, bullet \
lists, backticks or numbered sections. Lead with what the human now owns.
"""


class OpenAIPlanner:
    """Drives the agent loop with an OpenAI model, falling back when it can't."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        fallback: Optional[Any] = None,
        temperature: float = 0.0,
        max_tool_calls: int = 40,
        client: Optional[Any] = None,
        provider: str = "openai",
        min_interval_s: Optional[float] = None,
        rate_limit_retries: int = 2,
        backoff_s: float = 6.0,
    ):
        if provider not in PROVIDERS:
            raise RuntimeError(
                f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}."
            )
        config = PROVIDERS[provider]
        self.provider = provider
        self.model = (
            model
            or os.environ.get("SKYSOLVER_AGENT_MODEL")
            or config["default_model"]
        )
        self.name = f"{provider}:{self.model}"

        if client is not None:
            # Injected transport (tests, or another compatible provider).
            self._client = client
        else:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    "The openai package is required for the LLM planner: pip install openai"
                ) from exc

            key = api_key or _first_env(config["key_env"])
            if not key:
                names = " or ".join(config["key_env"])
                raise RuntimeError(
                    f"{names} is not set. Put it in .env at the repository root "
                    f"(get a key from {config['console']}), or run with "
                    "--planner deterministic."
                )
            # Fail over fast. The SDK retries twice by default, which is ~7s of
            # dead air in front of an audience before the fallback engages.
            self._client = OpenAI(
                api_key=key,
                base_url=config["base_url"],
                max_retries=1,
                timeout=30.0,
            )
        self._temperature = temperature
        self._max_tool_calls = max_tool_calls
        # The pace to fall back to once the provider pushes back. Not applied
        # until then: see _wait_for_slot.
        self._paced_interval_s = (
            min_interval_s if min_interval_s is not None else config.get("min_interval_s", 0.0)
        )
        self._min_interval_s = 0.0
        self._rate_limit_retries = rate_limit_retries
        self._backoff_s = backoff_s
        self._last_call_at = 0.0
        # Models to try, in order, before falling back to the deterministic
        # planner. Skips any that duplicate an explicitly requested model.
        self._model_queue = [m for m in config.get("fallback_models", ()) if m != self.model]
        self._fallback = fallback or DeterministicPlanner()
        self._degraded = False
        self._messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._pending_tool_call_id: Optional[str] = None
        self._tools: Optional[List[Dict[str, Any]]] = None
        self.events: List[str] = []
        self.handover: str = ""

    # -- Planner protocol --------------------------------------------------
    def propose(self, state: "WorldState") -> Optional[Decision]:
        if self._degraded:
            return self._fallback.propose(state)

        if self._tools is None:
            self._tools = [
                {"type": "function", "function": spec}
                for spec in _as_openai_functions(state.registry.anthropic_tools())
            ]
            self._messages.append({"role": "user", "content": _kickoff(state)})

        try:
            message = self._complete()
        except Exception as exc:  # network, auth, quota, transient 5xx
            # Quota is charged per model. Step down to a lighter model with its
            # own allowance before abandoning LLM planning altogether.
            if _is_rate_limit(exc) and self._step_down_model():
                try:
                    message = self._complete()
                except Exception as retry_exc:
                    self._degrade(_explain(retry_exc))
                    return self._fallback.propose(state)
            else:
                self._degrade(_explain(exc))
                return self._fallback.propose(state)

        if not getattr(message, "tool_calls", None):
            self.handover = (message.content or "").strip()
            return None

        call = message.tool_calls[0]
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        # The reason is an argument, not a side effect of narration — pull it
        # out before the call reaches the domain handlers.
        stated_reason = str(args.pop(RATIONALE_FIELD, "") or "").strip()

        # Echo the assistant turn back verbatim rather than rebuilding it.
        # Providers attach fields we must not drop: Gemini returns a
        # thought_signature under tool_calls[].extra_content.google, and omitting
        # it on the next request is rejected with a 400.
        self._messages.append(_as_message_dict(message))
        self._pending_tool_call_id = call.id

        narration = (message.content or "").strip()
        return Decision(
            tool=call.function.name,
            args=args,
            rationale=stated_reason or narration or "(model gave no stated reason)",
            phase=_phase_for(call.function.name),
        )

    def observe(self, decision: Decision, result: ToolResult) -> None:
        """Feed the tool result back so the model can re-plan against reality."""
        if self._degraded or self._pending_tool_call_id is None:
            return
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": self._pending_tool_call_id,
                "content": json.dumps(_compact(result.to_dict()))[:6000],
            }
        )
        self._pending_tool_call_id = None

    # -- internals ---------------------------------------------------------
    def _complete(self):
        """One model turn, paced and retried against transient rate limits.

        A 429 means one of two very different things: the request arrived too
        fast (transient — wait and it succeeds) or the allowance is spent
        (permanent — degrade). They are indistinguishable from the response, so
        retry a bounded number of times and treat continued failure as
        permanent.
        """
        last_error = None
        for attempt in range(self._rate_limit_retries + 1):
            self._wait_for_slot()
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=self._messages,
                    tools=self._tools,
                    tool_choice="auto",
                    parallel_tool_calls=False,
                    temperature=self._temperature,
                )
                return response.choices[0].message
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == self._rate_limit_retries:
                    raise
                # The provider has pushed back, so stop firing at full speed for
                # the rest of the run. Paying this cost only once we have
                # evidence we need it keeps an unconstrained run fast.
                self._engage_pacing()
                last_error = exc
                time.sleep(self._backoff_s * (2**attempt))
        raise last_error  # pragma: no cover - loop always returns or raises

    def _engage_pacing(self) -> None:
        if self._min_interval_s or not self._paced_interval_s:
            return
        self._min_interval_s = self._paced_interval_s
        self.events.append(
            f"Rate limited, so calls are now spaced {self._paced_interval_s:g}s apart "
            "for the rest of the run."
        )

    def _wait_for_slot(self) -> None:
        if self._min_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self._min_interval_s:
            time.sleep(self._min_interval_s - elapsed)
        self._last_call_at = time.monotonic()

    def _step_down_model(self) -> bool:
        """Move to the next model in the chain. False when none are left."""
        if not self._model_queue:
            return False
        previous = self.model
        self.model = self._model_queue.pop(0)
        self.name = f"{self.provider}:{self.model}"
        self.events.append(
            f"{previous} was out of quota, so the run continued on {self.model}."
        )
        return True

    def _degrade(self, reason: str) -> None:
        self._degraded = True
        self.name = f"{self.provider} → deterministic"
        # Kept to the cause only — the caller adds the reassurance, so stating
        # it here too reads as duplicated filler in the UI banner.
        self.events.append(
            f"{reason} Switched to the deterministic planner for the remainder of the run."
        )


def _explain(exc: Exception) -> str:
    """A one-line, operator-readable cause — not a raw provider stack trace."""
    if _is_rate_limit(exc):
        text = str(exc).lower()
        if "quota" in text or "billing" in text:
            return "The model provider's quota is exhausted."
        return "The model provider is rate limiting requests."
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "The model provider rejected the API key."
    if status == 404:
        return "The configured model is not available to this account."
    if status and status >= 500:
        return "The model provider returned a server error."
    return f"The model provider could not be reached ({type(exc).__name__})."


def _is_rate_limit(exc: Exception) -> bool:
    """Identify a 429 without importing provider exception types."""
    if type(exc).__name__ == "RateLimitError":
        return True
    return getattr(exc, "status_code", None) == 429


def _as_message_dict(message: Any) -> Dict[str, Any]:
    """Serialise an assistant message for replay, preserving provider extras."""
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    # Test doubles and non-pydantic transports.
    return {
        "role": "assistant",
        "content": getattr(message, "content", None),
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in (getattr(message, "tool_calls", None) or [])
        ],
    }


def _first_env(names) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


RATIONALE_FIELD = "why"
RATIONALE_DESCRIPTION = (
    "One sentence, for the duty manager's audit trail: why this action, on this "
    "flight, now — and why this candidate over the alternatives."
)


def _as_openai_functions(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Translate the registry's tool specs into OpenAI function definitions.

    Same names, same schemas — the tool surface is defined once, in
    ``agents.tools``, so both planners and any future provider see it identically.

    One addition is made here and only here: a required ``why`` argument on every
    tool. Models differ in whether they narrate alongside a tool call (Gemini
    usually returns none), and an unexplained action is useless in an audit
    trail. Making the reason an argument means the model cannot act without
    stating a reason. It is stripped before execution, so the domain handlers
    never see it.
    """
    functions = []
    for tool in tools:
        schema = tool["input_schema"]
        properties = dict(schema.get("properties", {}))
        properties[RATIONALE_FIELD] = {
            "type": "string",
            "description": RATIONALE_DESCRIPTION,
        }
        functions.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    **schema,
                    "properties": properties,
                    "required": [*schema.get("required", []), RATIONALE_FIELD],
                },
            }
        )
    return functions


def _kickoff(state: "WorldState") -> str:
    return (
        "An operational disruption is active. Recover the affected flights: for each "
        "flight whose crew is out of legal limits, either commit a replacement the "
        "rules engine has cleared, or escalate it to the human scheduler queue with a "
        "justification. Begin by reading the operational picture."
    )


def _phase_for(tool_name: str) -> str:
    return {
        "get_operational_picture": "perceive",
        "list_candidate_crew": "plan",
        "get_solver_tiers": "perceive",
        "escalate_to_tier3": "escalate",
    }.get(tool_name, "act")


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Trim tool output before it re-enters the context window.

    Full verdicts stay in the decision trace; the model only needs the fields it
    reasons over.
    """
    if not payload.get("ok"):
        return payload
    data = payload.get("data", {})
    if "rule_violations" in data:
        payload = dict(payload)
        payload["data"] = {
            "flight_id": data.get("flight_id"),
            "crew_id": data.get("crew_id"),
            "crew_name": data.get("crew_name"),
            "legal": data.get("legal"),
            "checks": data.get("checks"),
            "rule_violations": [
                {"code": v.get("code"), "message": v.get("message")}
                for v in data.get("rule_violations", [])
            ],
        }
    return payload
