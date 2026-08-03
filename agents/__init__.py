"""SkySolver Recovery Agent.

An agentic layer over the existing recovery stack.  The agent decides *what to
try*; the FAR117/DGCA-style rules engine decides *what is allowed*.  Every
proposed crew reassignment is validated by the real legality engine before it
can be committed, and that guard is enforced in code (see
``agents.tools.ToolRegistry``) rather than in a prompt — so an LLM planner
cannot bypass it.

Public surface::

    from agents import RecoveryAgent, DeterministicPlanner

    agent = RecoveryAgent(store)
    result = agent.run()
    result.trace.to_dict()
"""

from agents.planner import DeterministicPlanner, Decision, Planner
from agents.recovery_agent import AgentResult, RecoveryAgent, WorldState
from agents.tools import ToolRegistry, ToolResult, ToolSpec, build_registry
from agents.trace import AgentStep, DecisionTrace

PLANNERS = ("deterministic", "gemini", "openai")


def build_planner(kind: str = "deterministic", model=None):
    """Resolve a planner by name, shared by the CLI and the HTTP surface.

    Raises ``RuntimeError`` when an LLM planner is requested but not
    configured, so callers can degrade to ``DeterministicPlanner`` explicitly
    rather than silently.
    """
    if kind == "deterministic":
        return DeterministicPlanner()
    if kind not in PLANNERS:
        raise RuntimeError(f"Unknown planner '{kind}'. Choose one of: {', '.join(PLANNERS)}.")
    from agents.llm_planner import OpenAIPlanner  # imported lazily: needs the openai package

    return OpenAIPlanner(provider=kind, model=model, fallback=DeterministicPlanner())


__all__ = [
    "PLANNERS",
    "build_planner",
    "AgentResult",
    "AgentStep",
    "Decision",
    "DecisionTrace",
    "DeterministicPlanner",
    "Planner",
    "RecoveryAgent",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "WorldState",
    "build_registry",
]
