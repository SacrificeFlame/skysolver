"""Structured decision trace for an agent run.

The trace is the product, not a debug log: it is what a duty manager reads to
decide whether to trust the plan, and what an auditor reads afterwards to
reconstruct why a flight was reassigned or escalated.  Every step records the
tool that ran, the exact arguments, the planner's stated reason for choosing it,
and what the domain actually answered.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentStep:
    index: int
    phase: str                      # perceive | plan | act | observe | escalate
    tool: str
    tool_input: Dict[str, Any]
    rationale: str                  # why the planner chose this action
    outcome: str                    # short human-readable result
    observation: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    duration_ms: int = 0
    at: str = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionTrace:
    planner: str
    started_at: str = field(default_factory=_now)
    finished_at: Optional[str] = None
    steps: List[AgentStep] = field(default_factory=list)

    def add(self, step: AgentStep) -> AgentStep:
        self.steps.append(step)
        return step

    def next_index(self) -> int:
        return len(self.steps) + 1

    def close(self) -> None:
        self.finished_at = _now()

    @property
    def tool_calls(self) -> int:
        return len(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planner": self.planner,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "tool_calls": self.tool_calls,
            "steps": [s.to_dict() for s in self.steps],
        }

    def render(self) -> str:
        """Plain-text rendering used by the CLI runner."""
        lines = [f"decision trace - planner={self.planner}  steps={self.tool_calls}", ""]
        for step in self.steps:
            marker = " " if step.ok else "!"
            args = ", ".join(f"{k}={v}" for k, v in step.tool_input.items())
            lines.append(f"{marker}{step.index:>3}. [{step.phase}] {step.tool}({args})")
            if step.rationale:
                lines.append(f"        why: {step.rationale}")
            lines.append(f"        ->   {step.outcome}")
        return "\n".join(lines)
