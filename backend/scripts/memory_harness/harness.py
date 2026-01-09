#!/usr/bin/env python3
"""Memory Effectiveness Test Harness.

Runs A/B tests comparing agent performance with and without memory context.
Designed to be called incrementally from Claude Code sessions.

Usage:
    python harness.py status              # Show current progress
    python harness.py next                # Run next pending scenario
    python harness.py run <id> <mode>     # Run specific scenario (baseline|memory)
    python harness.py compare             # Generate comparison report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add backend to path for imports
BACKEND_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BACKEND_PATH))

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
)

HARNESS_DIR = Path(__file__).parent
SCENARIOS_FILE = HARNESS_DIR / "scenarios.json"
STATE_FILE = HARNESS_DIR / "results" / "state.json"
RESULTS_DIR = HARNESS_DIR / "results"

# Working directory for agent - the summitflow project root
WORKING_DIR = str(BACKEND_PATH.parent)


def load_scenarios() -> dict[str, Any]:
    """Load test scenarios from JSON."""
    with open(SCENARIOS_FILE) as f:
        return json.load(f)


def load_state() -> dict[str, Any]:
    """Load current harness state, creating if needed."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "runs": [],
        "current_mode": None,
    }


def save_state(state: dict[str, Any]) -> None:
    """Save harness state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(UTC).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_completed_runs(state: dict[str, Any]) -> set[tuple[str, str]]:
    """Get set of (scenario_id, mode) tuples that have been completed."""
    return {(r["scenario_id"], r["mode"]) for r in state.get("runs", [])}


def get_next_pending(scenarios: dict[str, Any], state: dict[str, Any]) -> tuple[str, str] | None:
    """Find the next pending scenario/mode combo.

    Order: all baseline first, then all memory-enabled.
    """
    completed = get_completed_runs(state)

    # First do all baseline runs
    for scenario in scenarios["scenarios"]:
        key = (scenario["id"], "baseline")
        if key not in completed:
            return key

    # Then all memory-enabled runs
    for scenario in scenarios["scenarios"]:
        key = (scenario["id"], "memory")
        if key not in completed:
            return key

    return None


async def run_scenario(
    scenario: dict[str, Any],
    mode: str,
    memory_context: str | None = None,
) -> dict[str, Any]:
    """Run a single scenario and collect metrics.

    Args:
        scenario: Scenario definition from scenarios.json
        mode: "baseline" or "memory"
        memory_context: Memory context to inject (for memory mode)

    Returns:
        Results dict with metrics
    """
    start_time = time.time()

    # Build prompt
    prompt = scenario["prompt"]
    if mode == "memory" and memory_context:
        prompt = f"""<memory-context>
{memory_context}
</memory-context>

{prompt}"""

    # Track metrics during execution
    tool_calls: list[dict[str, Any]] = []
    text_output: list[str] = []

    options = ClaudeAgentOptions(
        cwd=WORKING_DIR,
        permission_mode="bypassPermissions",  # Allow read tools
        model="sonnet",
    )

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_output.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_calls.append(
                            {
                                "tool": block.name,
                                "input": block.input if hasattr(block, "input") else {},
                                "timestamp": time.time() - start_time,
                            }
                        )

        end_time = time.time()
        success = True
        error = None

    except Exception as e:
        end_time = time.time()
        success = False
        error = str(e)

    return {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "mode": mode,
        "started_at": datetime.fromtimestamp(start_time, tz=UTC).isoformat(),
        "duration_seconds": round(end_time - start_time, 2),
        "tool_calls": tool_calls,
        "tool_call_count": len(tool_calls),
        "success": success,
        "error": error,
        "output_length": sum(len(t) for t in text_output),
        "output_preview": "".join(text_output)[:500] if text_output else None,
    }


async def fetch_memory_context(project_id: str = "summitflow") -> str | None:
    """Fetch memory context from the REAL session-start API.

    This calls the actual API that Claude Code's session-start hook uses,
    ensuring we test with real memory infrastructure.
    """
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://localhost:8001/api/projects/{project_id}/context/session-start",
                json={},  # Empty request body - API doesn't require fields
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("context_block", "")
            else:
                print(f"Warning: API returned {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"Warning: Could not fetch memory context: {e}")
    return None


def cmd_status(args: argparse.Namespace) -> None:
    """Show current harness status."""
    scenarios = load_scenarios()
    state = load_state()
    completed = get_completed_runs(state)

    total_scenarios = len(scenarios["scenarios"])
    total_runs_needed = total_scenarios * 2  # baseline + memory for each
    completed_count = len(completed)

    print("=" * 60)
    print(" MEMORY HARNESS STATUS")
    print("=" * 60)
    print(f"\nProgress: {completed_count}/{total_runs_needed} runs completed")
    print(f"Scenarios: {total_scenarios}")
    print()

    # Show per-scenario status
    print("Scenario Status:")
    print("-" * 60)
    for scenario in scenarios["scenarios"]:
        sid = scenario["id"]
        baseline_done = (sid, "baseline") in completed
        memory_done = (sid, "memory") in completed
        b_status = "Done" if baseline_done else "Pending"
        m_status = "Done" if memory_done else "Pending"
        print(f"  {sid:30} baseline:{b_status:8} memory:{m_status:8}")

    print()

    # Show next pending
    next_run = get_next_pending(scenarios, state)
    if next_run:
        print(f"Next run: {next_run[0]} ({next_run[1]})")
        print("\nRun with: python harness.py next")
    else:
        print("All runs complete! Run 'python harness.py compare' to see results.")


def cmd_next(args: argparse.Namespace) -> None:
    """Run the next pending scenario."""
    scenarios = load_scenarios()
    state = load_state()

    next_run = get_next_pending(scenarios, state)
    if not next_run:
        print("All runs complete! Use 'python harness.py compare' to see results.")
        return

    scenario_id, mode = next_run
    scenario = next(s for s in scenarios["scenarios"] if s["id"] == scenario_id)

    print(f"Running: {scenario_id} ({mode})")
    print("-" * 60)

    # Fetch memory context if needed
    memory_context = None
    if mode == "memory":
        print("Fetching memory context...")
        memory_context = asyncio.run(fetch_memory_context())
        if memory_context:
            print(f"  Injected {len(memory_context)} chars of memory context")
        else:
            print("  Warning: No memory context available")

    # Run the scenario
    print(f"Executing scenario: {scenario['name']}...")
    result = asyncio.run(run_scenario(scenario, mode, memory_context))

    # Save result
    result_file = RESULTS_DIR / mode / f"{scenario_id}.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    # Update state
    state["runs"].append(
        {
            "scenario_id": scenario_id,
            "mode": mode,
            "completed_at": datetime.now(UTC).isoformat(),
            "result_file": str(result_file.relative_to(HARNESS_DIR)),
        }
    )
    save_state(state)

    # Print summary
    print()
    print("=" * 60)
    print(f" RESULT: {scenario_id} ({mode})")
    print("=" * 60)
    print(f"  Duration: {result['duration_seconds']}s")
    print(f"  Tool calls: {result['tool_call_count']}")
    print(f"  Success: {result['success']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print(f"  Saved to: {result_file}")

    # Show what's next
    next_run = get_next_pending(scenarios, state)
    if next_run:
        print(f"\nNext: {next_run[0]} ({next_run[1]})")
        print("Continue with: python harness.py next")


def cmd_run(args: argparse.Namespace) -> None:
    """Run a specific scenario."""
    scenarios = load_scenarios()
    state = load_state()

    scenario = next((s for s in scenarios["scenarios"] if s["id"] == args.scenario), None)
    if not scenario:
        print(f"Error: Scenario '{args.scenario}' not found")
        sys.exit(1)

    mode = args.mode
    if mode not in ("baseline", "memory"):
        print(f"Error: Mode must be 'baseline' or 'memory', got '{mode}'")
        sys.exit(1)

    # Check if already done
    completed = get_completed_runs(state)
    if (args.scenario, mode) in completed and not args.force:
        print(f"Already completed: {args.scenario} ({mode})")
        print("Use --force to re-run")
        return

    print(f"Running: {args.scenario} ({mode})")
    print("-" * 60)

    # Fetch memory context if needed
    memory_context = None
    if mode == "memory":
        print("Fetching memory context...")
        memory_context = asyncio.run(fetch_memory_context())
        if memory_context:
            print(f"  Injected {len(memory_context)} chars of memory context")

    # Run the scenario
    print(f"Executing scenario: {scenario['name']}...")
    result = asyncio.run(run_scenario(scenario, mode, memory_context))

    # Save result
    result_file = RESULTS_DIR / mode / f"{args.scenario}.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    # Update state (remove old run if force)
    if args.force:
        state["runs"] = [
            r
            for r in state["runs"]
            if not (r["scenario_id"] == args.scenario and r["mode"] == mode)
        ]

    state["runs"].append(
        {
            "scenario_id": args.scenario,
            "mode": mode,
            "completed_at": datetime.now(UTC).isoformat(),
            "result_file": str(result_file.relative_to(HARNESS_DIR)),
        }
    )
    save_state(state)

    # Print summary
    print()
    print(f"Duration: {result['duration_seconds']}s")
    print(f"Tool calls: {result['tool_call_count']}")
    print(f"Success: {result['success']}")


def cmd_compare(args: argparse.Namespace) -> None:
    """Generate comparison report."""
    scenarios = load_scenarios()

    print("=" * 70)
    print(" MEMORY EFFECTIVENESS COMPARISON")
    print("=" * 70)
    print()

    # Load all results
    baseline_results: dict[str, dict] = {}
    memory_results: dict[str, dict] = {}

    for scenario in scenarios["scenarios"]:
        sid = scenario["id"]

        baseline_file = RESULTS_DIR / "baseline" / f"{sid}.json"
        if baseline_file.exists():
            with open(baseline_file) as f:
                baseline_results[sid] = json.load(f)

        memory_file = RESULTS_DIR / "memory" / f"{sid}.json"
        if memory_file.exists():
            with open(memory_file) as f:
                memory_results[sid] = json.load(f)

    if not baseline_results or not memory_results:
        print("Not enough data for comparison.")
        print(f"  Baseline runs: {len(baseline_results)}")
        print(f"  Memory runs: {len(memory_results)}")
        return

    # Per-scenario comparison
    print(f"{'Scenario':<25} {'Baseline':>12} {'Memory':>12} {'Diff':>10}")
    print(f"{'':25} {'Tools/Time':>12} {'Tools/Time':>12} {'Tools':>10}")
    print("-" * 70)

    total_baseline_tools = 0
    total_memory_tools = 0
    total_baseline_time = 0.0
    total_memory_time = 0.0
    scenarios_compared = 0

    for scenario in scenarios["scenarios"]:
        sid = scenario["id"]
        if sid in baseline_results and sid in memory_results:
            b = baseline_results[sid]
            m = memory_results[sid]

            b_tools = b["tool_call_count"]
            m_tools = m["tool_call_count"]
            b_time = b["duration_seconds"]
            m_time = m["duration_seconds"]

            diff = m_tools - b_tools
            diff_str = f"{diff:+d}" if diff != 0 else "0"

            print(
                f"{sid:<25} {b_tools:>5}/{b_time:>5.1f}s {m_tools:>5}/{m_time:>5.1f}s {diff_str:>10}"
            )

            total_baseline_tools += b_tools
            total_memory_tools += m_tools
            total_baseline_time += b_time
            total_memory_time += m_time
            scenarios_compared += 1

    if scenarios_compared > 0:
        print("-" * 70)

        tool_diff = total_memory_tools - total_baseline_tools
        tool_pct = (
            ((total_memory_tools - total_baseline_tools) / total_baseline_tools * 100)
            if total_baseline_tools > 0
            else 0
        )
        time_diff = total_memory_time - total_baseline_time
        time_pct = (
            ((total_memory_time - total_baseline_time) / total_baseline_time * 100)
            if total_baseline_time > 0
            else 0
        )

        print(
            f"{'TOTAL':<25} {total_baseline_tools:>5}/{total_baseline_time:>5.1f}s {total_memory_tools:>5}/{total_memory_time:>5.1f}s {tool_diff:>+10d}"
        )
        print()
        print("=" * 70)
        print(" SUMMARY")
        print("=" * 70)
        print(f"  Scenarios compared: {scenarios_compared}")
        print(f"  Tool call change: {tool_diff:+d} ({tool_pct:+.1f}%)")
        print(f"  Time change: {time_diff:+.1f}s ({time_pct:+.1f}%)")
        print()

        if tool_pct < -10:
            print("  RESULT: Memory REDUCES tool calls significantly")
        elif tool_pct > 10:
            print("  RESULT: Memory INCREASES tool calls (investigate)")
        else:
            print("  RESULT: Memory has minimal impact on tool calls")

    # Save report
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scenarios_compared": scenarios_compared,
        "baseline_total_tools": total_baseline_tools,
        "memory_total_tools": total_memory_tools,
        "baseline_total_time": total_baseline_time,
        "memory_total_time": total_memory_time,
        "tool_change_percent": tool_pct,
        "time_change_percent": time_pct,
    }

    report_file = RESULTS_DIR / "comparison_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory Effectiveness Test Harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status command
    subparsers.add_parser("status", help="Show current progress")

    # next command
    subparsers.add_parser("next", help="Run next pending scenario")

    # run command
    run_parser = subparsers.add_parser("run", help="Run specific scenario")
    run_parser.add_argument("scenario", help="Scenario ID")
    run_parser.add_argument("mode", help="Mode: baseline or memory")
    run_parser.add_argument("--force", action="store_true", help="Re-run even if completed")

    # compare command
    subparsers.add_parser("compare", help="Generate comparison report")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "next":
        cmd_next(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "compare":
        cmd_compare(args)


if __name__ == "__main__":
    main()
