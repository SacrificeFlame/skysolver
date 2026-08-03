"""Run the recovery agent from the command line.

    python -m agents                     # deterministic planner, no API key
    python -m agents --planner gemini    # Gemini planner (needs GEMINI_API_KEY)
    python -m agents --planner openai    # OpenAI planner (needs OPENAI_API_KEY)
    python -m agents --json              # machine-readable result
"""

from __future__ import annotations

import argparse
import json
import sys

from agents.planner import DeterministicPlanner
from agents.recovery_agent import RecoveryAgent
from deployment.recovery_api import RecoveryStore


def _build_planner(kind: str, model):
    from agents import build_planner

    return build_planner("openai" if kind == "llm" else kind, model=model)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agents", description="SkySolver recovery agent")
    parser.add_argument("--json", action="store_true", help="emit the full result as JSON")
    parser.add_argument(
        "--planner",
        choices=["deterministic", "gemini", "openai", "llm"],
        default="deterministic",
        help=(
            "deterministic (no API key), gemini (GEMINI_API_KEY) or openai "
            "(OPENAI_API_KEY). LLM planners fall back to deterministic on failure."
        ),
    )
    parser.add_argument("--model", default=None, help="override the LLM model id")
    parser.add_argument("--max-steps", type=int, default=40)
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    try:
        planner = _build_planner(args.planner, args.model)
    except RuntimeError as exc:
        print(f"{exc}\nFalling back to the deterministic planner.", file=sys.stderr)
        planner = DeterministicPlanner()

    agent = RecoveryAgent(RecoveryStore(), planner=planner, max_steps=args.max_steps)
    result = agent.run()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(result.trace.render())
    for note in result.notes:
        print(f"\n  ! {note}")
    print()
    print("plan")
    print("----")
    for item in result.resolved:
        print(f"  RESOLVED  {item['flight_id']} <- {item['crew_id']} {item['crew_name']}")
        print(f"            {item['rationale']}")
    for item in result.escalated:
        print(f"  ESCALATED {item['flight_id']} ({item['passengers']} passengers)")
        print(f"            {item['reason']}")
    for flight_id in result.unresolved:
        print(f"  OPEN      {flight_id}")
    if result.handover:
        print()
        print("handover")
        print("--------")
        print(f"  {result.handover}")
    summary = result.to_dict()["summary"]
    print()
    print(
        f"{summary['resolved']} resolved, {summary['escalated']} escalated, "
        f"{summary['unresolved']} unresolved in {summary['tool_calls']} tool calls "
        f"({summary['elapsed_s']}s) — {summary['stopped_because']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
