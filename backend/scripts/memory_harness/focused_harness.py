#!/usr/bin/env python3
"""Focused Memory Effectiveness Harness.

Based on real agent search patterns from session history.
Runs 3 baseline + 3 memory tests per scenario for statistical comparison.

Usage:
    python focused_harness.py status           # Show progress
    python focused_harness.py run <scenario>   # Run one scenario (3+3)
    python focused_harness.py run-all          # Run all scenarios
    python focused_harness.py report           # Generate comparison report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add backend to path
BACKEND_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BACKEND_PATH))

from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: E402
from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock  # noqa: E402

HARNESS_DIR = Path(__file__).parent
SCENARIOS_FILE = HARNESS_DIR / "focused_scenarios.json"
RESULTS_FILE = HARNESS_DIR / "results" / "focused_results.json"
WORKING_DIR = str(BACKEND_PATH.parent)


def load_scenarios() -> dict[str, Any]:
    with open(SCENARIOS_FILE) as f:
        return json.load(f)


def load_results() -> dict[str, Any]:
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {"scenarios": {}, "created_at": datetime.now(UTC).isoformat()}


def save_results(results: dict[str, Any]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    results["updated_at"] = datetime.now(UTC).isoformat()
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


async def run_single(prompt: str, context: str | None = None) -> dict[str, Any]:
    """Run a single agent query and track tool calls."""
    start_time = time.time()

    full_prompt = prompt
    if context:
        full_prompt = f"{context}\n\n{prompt}"

    tool_calls: list[dict[str, Any]] = []
    text_output: list[str] = []

    options = ClaudeAgentOptions(
        cwd=WORKING_DIR,
        permission_mode="bypassPermissions",
        model="haiku",  # Fast model for focused tests
    )

    try:
        async for message in query(prompt=full_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_output.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_calls.append(
                            {
                                "tool": block.name,
                                "timestamp": time.time() - start_time,
                            }
                        )

        return {
            "success": True,
            "duration": round(time.time() - start_time, 2),
            "tool_calls": len(tool_calls),
            "tool_types": [t["tool"] for t in tool_calls],
            "output": "".join(text_output)[:500],
        }

    except Exception as e:
        return {
            "success": False,
            "duration": round(time.time() - start_time, 2),
            "tool_calls": len(tool_calls),
            "error": str(e),
        }


async def run_scenario(scenario: dict[str, Any], runs: int = 3) -> dict[str, Any]:
    """Run a scenario with baseline and memory tests."""
    scenario_id = scenario["id"]
    prompt = scenario["prompt"]
    memory_hint = scenario["memory_hint"]
    context_template = (
        "## Project Knowledge\n\n{hint}\n\nUse this context - don't search unnecessarily."
    )

    print(f"\n{'=' * 60}")
    print(f" SCENARIO: {scenario['name']}")
    print(f"{'=' * 60}")

    # Baseline runs
    print(f"\nRunning {runs} baseline tests...")
    baseline_results = []
    for i in range(runs):
        print(f"  Baseline {i + 1}/{runs}...", end=" ", flush=True)
        result = await run_single(prompt)
        baseline_results.append(result)
        print(f"{result['tool_calls']} tools, {result['duration']}s")

    # Memory runs
    print(f"\nRunning {runs} memory tests...")
    memory_context = context_template.format(hint=memory_hint)
    memory_results = []
    for i in range(runs):
        print(f"  Memory {i + 1}/{runs}...", end=" ", flush=True)
        result = await run_single(prompt, memory_context)
        memory_results.append(result)
        print(f"{result['tool_calls']} tools, {result['duration']}s")

    # Calculate statistics
    baseline_tools = [r["tool_calls"] for r in baseline_results]
    memory_tools = [r["tool_calls"] for r in memory_results]

    baseline_avg = statistics.mean(baseline_tools)
    memory_avg = statistics.mean(memory_tools)
    reduction = ((baseline_avg - memory_avg) / baseline_avg * 100) if baseline_avg > 0 else 0

    summary = {
        "scenario_id": scenario_id,
        "runs_per_mode": runs,
        "baseline": {
            "tool_calls": baseline_tools,
            "avg": round(baseline_avg, 2),
            "results": baseline_results,
        },
        "memory": {
            "tool_calls": memory_tools,
            "avg": round(memory_avg, 2),
            "results": memory_results,
        },
        "reduction_pct": round(reduction, 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }

    # Print summary
    print(f"\n{'─' * 60}")
    print(f" RESULT: {scenario['name']}")
    print(f"{'─' * 60}")
    print(f"  Baseline avg: {baseline_avg:.1f} tool calls")
    print(f"  Memory avg:   {memory_avg:.1f} tool calls")
    print(f"  Reduction:    {reduction:+.1f}%")

    return summary


def cmd_status(args: argparse.Namespace) -> None:
    """Show current progress."""
    scenarios = load_scenarios()
    results = load_results()

    print("=" * 60)
    print(" FOCUSED HARNESS STATUS")
    print("=" * 60)

    total = len(scenarios["scenarios"])
    completed = len(results.get("scenarios", {}))

    print(f"\nProgress: {completed}/{total} scenarios completed")
    print()

    for s in scenarios["scenarios"]:
        sid = s["id"]
        if sid in results.get("scenarios", {}):
            r = results["scenarios"][sid]
            reduction = r.get("reduction_pct", 0)
            status = f"Done ({reduction:+.1f}%)"
        else:
            status = "Pending"
        print(f"  {sid:25} {status}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run a specific scenario."""
    scenarios = load_scenarios()
    results = load_results()

    scenario = next((s for s in scenarios["scenarios"] if s["id"] == args.scenario), None)
    if not scenario:
        print(f"Scenario not found: {args.scenario}")
        sys.exit(1)

    # Run the scenario
    summary = asyncio.run(run_scenario(scenario, runs=args.runs))

    # Save results
    if "scenarios" not in results:
        results["scenarios"] = {}
    results["scenarios"][args.scenario] = summary
    save_results(results)

    print(f"\nSaved to: {RESULTS_FILE}")


def cmd_run_all(args: argparse.Namespace) -> None:
    """Run all scenarios."""
    scenarios = load_scenarios()
    results = load_results()

    for scenario in scenarios["scenarios"]:
        sid = scenario["id"]
        if sid in results.get("scenarios", {}) and not args.force:
            print(f"\nSkipping {sid} (already done, use --force to re-run)")
            continue

        summary = asyncio.run(run_scenario(scenario, runs=args.runs))

        if "scenarios" not in results:
            results["scenarios"] = {}
        results["scenarios"][sid] = summary
        save_results(results)

    # Generate report
    cmd_report(args)


def cmd_report(args: argparse.Namespace) -> None:
    """Generate comparison report."""
    results = load_results()

    if not results.get("scenarios"):
        print("No results yet. Run some scenarios first.")
        return

    print("\n" + "=" * 70)
    print(" MEMORY EFFECTIVENESS REPORT")
    print("=" * 70)
    print()
    print(f"{'Scenario':<30} {'Baseline':>10} {'Memory':>10} {'Reduction':>12}")
    print("-" * 70)

    total_baseline = 0
    total_memory = 0

    for sid, data in results["scenarios"].items():
        b_avg = data["baseline"]["avg"]
        m_avg = data["memory"]["avg"]
        reduction = data["reduction_pct"]

        total_baseline += b_avg
        total_memory += m_avg

        print(f"{sid:<30} {b_avg:>10.1f} {m_avg:>10.1f} {reduction:>+11.1f}%")

    print("-" * 70)

    overall_reduction = (
        ((total_baseline - total_memory) / total_baseline * 100) if total_baseline > 0 else 0
    )
    print(
        f"{'AVERAGE':<30} {total_baseline / len(results['scenarios']):>10.1f} {total_memory / len(results['scenarios']):>10.1f} {overall_reduction:>+11.1f}%"
    )

    print()
    print("=" * 70)
    print(" CONCLUSION")
    print("=" * 70)
    if overall_reduction > 20:
        print("  Memory SIGNIFICANTLY reduces tool calls (>20%)")
    elif overall_reduction > 0:
        print("  Memory provides MODERATE benefit")
    else:
        print("  Memory shows NO benefit - investigate scenarios")


def main() -> None:
    parser = argparse.ArgumentParser(description="Focused Memory Harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show progress")

    run_parser = subparsers.add_parser("run", help="Run specific scenario")
    run_parser.add_argument("scenario", help="Scenario ID")
    run_parser.add_argument("--runs", type=int, default=3, help="Runs per mode")

    all_parser = subparsers.add_parser("run-all", help="Run all scenarios")
    all_parser.add_argument("--runs", type=int, default=3, help="Runs per mode")
    all_parser.add_argument("--force", action="store_true", help="Re-run completed")

    subparsers.add_parser("report", help="Generate report")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "run-all":
        cmd_run_all(args)
    elif args.command == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
