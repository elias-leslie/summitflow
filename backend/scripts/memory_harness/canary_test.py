#!/usr/bin/env python3
"""Memory Canary Tests - Verify the plumbing works.

These tests inject a unique hash and verify agents can find it.
If these fail, nothing else will work.

Test layers:
1. Hash in context_block → does agent read context at all?
2. Hash in pattern (expand required) → does progressive disclosure work?

Usage:
    python canary_test.py layer1          # Test context_block reading
    python canary_test.py layer2          # Test pattern expand flow
    python canary_test.py all             # Run all canary tests
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from pathlib import Path

# Add backend to path
BACKEND_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BACKEND_PATH))

import httpx
from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

API_BASE = "http://localhost:8001"
PROJECT_ID = "summitflow"
WORKING_DIR = str(BACKEND_PATH.parent)


def generate_hash() -> str:
    """Generate a unique 8-char hash for this test run."""
    return hashlib.md5(f"canary-{time.time()}".encode()).hexdigest()[:8]


async def run_agent(prompt: str, context: str | None = None, verbose: bool = False) -> dict:
    """Run agent and track results.

    Args:
        prompt: The prompt to send
        context: Optional context to inject
        verbose: If True, print every tool call and its result
    """
    start = time.time()

    full_prompt = prompt
    if context:
        full_prompt = f"<memory-context>\n{context}\n</memory-context>\n\n{prompt}"

    tool_calls = []
    text_output = []

    options = ClaudeAgentOptions(
        cwd=WORKING_DIR,
        permission_mode="bypassPermissions",
        model="haiku",  # Fast model for canary tests
    )

    if verbose:
        print(f"\n{'─' * 50}")
        print(f"PROMPT: {prompt[:100]}...")
        if context:
            print(f"CONTEXT: {context[:100]}...")
        print(f"{'─' * 50}")

    try:
        async for message in query(prompt=full_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_output.append(block.text)
                        if verbose:
                            print(f"TEXT: {block.text[:200]}...")
                    elif isinstance(block, ToolUseBlock):
                        tool_info = {
                            "name": block.name,
                            "input": getattr(block, "input", {}),
                        }
                        tool_calls.append(tool_info)
                        if verbose:
                            input_str = str(tool_info["input"])[:100]
                            print(f"TOOL: {block.name} → {input_str}")

        if verbose:
            print(f"{'─' * 50}")

        return {
            "success": True,
            "duration": round(time.time() - start, 2),
            "tool_calls": len(tool_calls),
            "tool_types": [t["name"] for t in tool_calls],
            "tool_details": tool_calls,
            "output": "".join(text_output),
        }
    except Exception as e:
        return {
            "success": False,
            "duration": round(time.time() - start, 2),
            "tool_calls": len(tool_calls),
            "error": str(e),
            "output": "".join(text_output),
        }


def test_layer1_context_block(runs: int = 5):
    """Layer 1: Can agent read context_block?

    Inject hash directly into context, ask agent to report it.
    Expected: Agent finds hash with 0 tool calls (just reads context).
    """
    print("=" * 60)
    print(f" LAYER 1: Context Block Reading ({runs} runs)")
    print("=" * 60)

    results = []
    for i in range(runs):
        test_hash = generate_hash()

        context = f"""## Test Context

CANARY_VERIFICATION_CODE: {test_hash}

This code is for testing purposes only.
"""

        prompt = """What is the CANARY_VERIFICATION_CODE in your context?

Reply with ONLY the 8-character code, nothing else.
Do not search files - the code is in your context above."""

        print(f"\n  Run {i + 1}/{runs} (hash: {test_hash})...", end=" ", flush=True)
        result = asyncio.run(run_agent(prompt, context))

        found = test_hash in result["output"]
        results.append(
            {
                "found": found,
                "tool_calls": result["tool_calls"],
                "duration": result["duration"],
            }
        )

        status = "✓" if found and result["tool_calls"] == 0 else "✗"
        print(f"{status} {result['tool_calls']} tools, {result['duration']}s")

    # Calculate stats
    success_count = sum(1 for r in results if r["found"] and r["tool_calls"] == 0)
    found_count = sum(1 for r in results if r["found"])
    avg_tools = sum(r["tool_calls"] for r in results) / runs
    avg_duration = sum(r["duration"] for r in results) / runs

    print("\n" + "-" * 60)
    print(f" RESULTS ({runs} runs):")
    print(f"   Success rate: {success_count}/{runs} ({100 * success_count / runs:.0f}%)")
    print(f"   Found hash: {found_count}/{runs}")
    print(f"   Avg tool calls: {avg_tools:.1f}")
    print(f"   Avg duration: {avg_duration:.1f}s")

    # Pass if >= 80% success rate
    if success_count / runs >= 0.8:
        print(f"\n ✓ PASS: {100 * success_count / runs:.0f}% success rate")
        return True
    else:
        print(f"\n ✗ FAIL: Only {100 * success_count / runs:.0f}% success rate (need 80%+)")
        return False


def test_layer2_pattern_expand(runs: int = 5):
    """Layer 2: Does progressive disclosure work?

    Create a pattern with hash in content (not title).
    Agent must: see patterns_index → expand pattern → find hash.
    """
    print("=" * 60)
    print(f" LAYER 2: Pattern Expand ({runs} runs)")
    print("=" * 60)

    from app.storage.memory_patterns import create_pattern, update_pattern_status

    results = []
    for i in range(runs):
        test_hash = generate_hash()

        # Create a test pattern
        try:
            pattern = create_pattern(
                project_id=PROJECT_ID,
                pattern_type="test",
                title=f"Canary Test Pattern {test_hash}",
                content=f"CANARY_SECRET_HASH: {test_hash}\n\nThis pattern is for testing.",
                action="add",
                rationale="Canary test",
                confidence=1.0,
                skip_memory_check=True,
            )
            if pattern:
                pattern_id = pattern["id"]
                update_pattern_status(pattern_id, "applied")
            else:
                print(f"  Run {i + 1}: Failed to create pattern")
                continue
        except Exception as e:
            print(f"  Run {i + 1}: Error - {e}")
            continue

        # Build context
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{API_BASE}/api/projects/{PROJECT_ID}/context/session-start",
                json={},
            )
            data = resp.json()

        patterns_index = data.get("patterns_index", [])
        index_preview = "\n".join(f"  - {p['id']}: {p['title']}" for p in patterns_index[:10])

        context = f"## Available Patterns\n{index_preview}\n..."
        prompt = f"""Find the CANARY_SECRET_HASH for pattern "Canary Test Pattern {test_hash}".
Use curl http://localhost:8001/api/projects/summitflow/patterns to fetch patterns.
Reply with ONLY the 8-character hash value."""

        print(f"\n  Run {i + 1}/{runs} (hash: {test_hash})...", end=" ", flush=True)
        result = asyncio.run(run_agent(prompt, context))

        found = test_hash in result["output"]
        results.append(
            {
                "found": found,
                "tool_calls": result["tool_calls"],
                "duration": result["duration"],
            }
        )

        # Cleanup
        try:
            update_pattern_status(pattern_id, "rejected")
        except Exception:
            pass

        status = "✓" if found else "✗"
        print(f"{status} {result['tool_calls']} tools, {result['duration']}s")

    # Calculate stats
    success_count = sum(1 for r in results if r["found"])
    avg_tools = sum(r["tool_calls"] for r in results) / len(results) if results else 0
    avg_duration = sum(r["duration"] for r in results) / len(results) if results else 0

    print("\n" + "-" * 60)
    print(f" RESULTS ({len(results)} runs):")
    print(
        f"   Success rate: {success_count}/{len(results)} ({100 * success_count / len(results):.0f}%)"
    )
    print(f"   Avg tool calls: {avg_tools:.1f}")
    print(f"   Avg duration: {avg_duration:.1f}s")

    if success_count / len(results) >= 0.8:
        print(f"\n ✓ PASS: {100 * success_count / len(results):.0f}% success rate")
        return True
    else:
        print(f"\n ✗ FAIL: Only {100 * success_count / len(results):.0f}% success rate")
        return False


def test_layer3_baseline_comparison(runs: int = 3):
    """Layer 3: Compare baseline vs memory-enabled.

    Hash exists ONLY in memory (not in any file).
    Baseline should fail, memory-enabled should succeed.
    """
    print("=" * 60)
    print(f" LAYER 3: Baseline vs Memory ({runs} runs each)")
    print("=" * 60)

    from app.storage.memory_patterns import create_pattern, update_pattern_status

    baseline_results = []
    memory_results = []

    for i in range(runs):
        test_hash = generate_hash()
        print(f"\n  Run {i + 1}/{runs} (hash: {test_hash})")

        # Create pattern with hash
        try:
            pattern = create_pattern(
                project_id=PROJECT_ID,
                pattern_type="test",
                title=f"Secret Canary Code {test_hash}",
                content=f"The secret canary code is: {test_hash}",
                action="add",
                rationale="Baseline comparison test",
                confidence=1.0,
                skip_memory_check=True,
            )
            if pattern:
                pattern_id = pattern["id"]
                update_pattern_status(pattern_id, "applied")
            else:
                continue
        except Exception as e:
            print(f"    Error: {e}")
            continue

        # Baseline
        prompt_baseline = f"""Find the secret canary code in this project.
Search the codebase for any file containing "{test_hash}".
Reply with the code if found, or "NOT_FOUND" if you cannot find it."""

        print("    Baseline...", end=" ", flush=True)
        baseline = asyncio.run(run_agent(prompt_baseline))
        baseline_found = test_hash in baseline["output"]
        baseline_results.append(
            {
                "found": baseline_found,
                "tool_calls": baseline["tool_calls"],
            }
        )
        print(f"{'✓' if baseline_found else '✗'} {baseline['tool_calls']} tools")

        # Memory-enabled
        prompt_memory = f"""Find the secret canary code "{test_hash}".
Use curl http://localhost:8001/api/projects/summitflow/patterns to fetch patterns.
Reply with ONLY the code value."""

        context = "Memory patterns available via curl"
        print("    Memory...", end=" ", flush=True)
        memory = asyncio.run(run_agent(prompt_memory, context))
        memory_found = test_hash in memory["output"]
        memory_results.append(
            {
                "found": memory_found,
                "tool_calls": memory["tool_calls"],
            }
        )
        print(f"{'✓' if memory_found else '✗'} {memory['tool_calls']} tools")

        # Cleanup
        try:
            update_pattern_status(pattern_id, "rejected")
        except Exception:
            pass

    # Calculate stats
    baseline_success = sum(1 for r in baseline_results if r["found"])
    memory_success = sum(1 for r in memory_results if r["found"])
    baseline_avg_tools = (
        sum(r["tool_calls"] for r in baseline_results) / len(baseline_results)
        if baseline_results
        else 0
    )
    memory_avg_tools = (
        sum(r["tool_calls"] for r in memory_results) / len(memory_results) if memory_results else 0
    )

    print("\n" + "-" * 60)
    print(f" RESULTS ({runs} runs):")
    print(f"   Baseline: {baseline_success}/{runs} success, avg {baseline_avg_tools:.1f} tools")
    print(f"   Memory:   {memory_success}/{runs} success, avg {memory_avg_tools:.1f} tools")

    # Memory should succeed more often than baseline
    if memory_success > baseline_success:
        print(f"\n ✓ PASS: Memory improves success rate ({baseline_success} → {memory_success})")
        return True
    elif memory_success == runs and baseline_success == runs:
        tool_reduction = baseline_avg_tools - memory_avg_tools
        if tool_reduction > 0:
            print(f"\n ✓ PASS: Both succeed, memory uses {tool_reduction:.1f} fewer tools")
            return True
        else:
            print("\n ~ NEUTRAL: Both succeed with similar tool usage")
            return True
    elif memory_success >= baseline_success:
        print(f"\n ~ NEUTRAL: Memory matches baseline ({memory_success}/{runs})")
        return memory_success > 0
    else:
        print("\n ✗ FAIL: Memory worse than baseline")
        return False


def test_fair_comparison(runs: int = 3, verbose: bool = True):
    """FAIR TEST: No hints, throw agent to the wolves.

    Creates a secret that exists ONLY in memory.
    Both agents get the SAME vague prompt.
    Difference: memory agent has the patterns API mentioned in context.

    This tests: does memory actually help when agent isn't told what to do?
    """
    print("=" * 60)
    print(f" FAIR TEST: No Hints ({runs} runs, verbose={verbose})")
    print("=" * 60)
    print("\nThis test does NOT tell agents how to find the secret.")
    print("Both get the same vague prompt. Memory agent just knows")
    print("that a memory API exists - not how to use it.\n")

    from app.storage.memory_patterns import create_pattern, update_pattern_status

    baseline_results = []
    memory_results = []

    for i in range(runs):
        test_hash = generate_hash()
        print(f"\n{'=' * 60}")
        print(f" RUN {i + 1}/{runs} - Secret: {test_hash}")
        print(f"{'=' * 60}")

        # Create pattern with secret
        try:
            pattern = create_pattern(
                project_id=PROJECT_ID,
                pattern_type="secret",
                title=f"Project Secret {test_hash[:4]}",
                content=f"The project secret code is: {test_hash}",
                action="add",
                rationale="Fair comparison test",
                confidence=1.0,
                skip_memory_check=True,
            )
            if pattern:
                pattern_id = pattern["id"]
                update_pattern_status(pattern_id, "applied")
                print(f"Secret stored in memory as pattern: {pattern_id[:8]}...")
            else:
                continue
        except Exception as e:
            print(f"Error: {e}")
            continue

        # SAME vague prompt for both - no hints about HOW
        base_prompt = f"""Find the project secret code.

The code is an 8-character string: {test_hash[:2]}******

Search wherever you need to. Report the full code when found.
If you cannot find it, say "NOT_FOUND"."""

        # Baseline: no context at all
        print("\n--- BASELINE (no memory context) ---")
        baseline = asyncio.run(run_agent(base_prompt, context=None, verbose=verbose))
        baseline_found = test_hash in baseline["output"]
        baseline_results.append(
            {
                "found": baseline_found,
                "tool_calls": baseline["tool_calls"],
                "tools": baseline["tool_types"],
            }
        )
        print(
            f"Result: {'FOUND' if baseline_found else 'NOT FOUND'} ({baseline['tool_calls']} tools)"
        )

        # Memory: only context is that memory API exists (not how to use it)
        print("\n--- MEMORY (knows API exists) ---")
        memory_context = """Project has a memory system at http://localhost:8001/api/
Patterns, observations, and project knowledge are stored there."""

        memory = asyncio.run(run_agent(base_prompt, context=memory_context, verbose=verbose))
        memory_found = test_hash in memory["output"]
        memory_results.append(
            {
                "found": memory_found,
                "tool_calls": memory["tool_calls"],
                "tools": memory["tool_types"],
            }
        )
        print(f"Result: {'FOUND' if memory_found else 'NOT FOUND'} ({memory['tool_calls']} tools)")

        # Cleanup
        try:
            update_pattern_status(pattern_id, "rejected")
        except Exception:
            pass

    # Summary
    baseline_success = sum(1 for r in baseline_results if r["found"])
    memory_success = sum(1 for r in memory_results if r["found"])
    baseline_avg_tools = (
        sum(r["tool_calls"] for r in baseline_results) / len(baseline_results)
        if baseline_results
        else 0
    )
    memory_avg_tools = (
        sum(r["tool_calls"] for r in memory_results) / len(memory_results) if memory_results else 0
    )

    print(f"\n{'=' * 60}")
    print(f" FINAL RESULTS ({runs} runs)")
    print(f"{'=' * 60}")
    print(f"   Baseline: {baseline_success}/{runs} found, avg {baseline_avg_tools:.1f} tools")
    print(f"   Memory:   {memory_success}/{runs} found, avg {memory_avg_tools:.1f} tools")

    if memory_success > baseline_success:
        print(f"\n ✓ MEMORY HELPS: +{memory_success - baseline_success} success rate")
        return True
    elif memory_success == baseline_success:
        if memory_avg_tools < baseline_avg_tools:
            print("\n ~ NEUTRAL: Same success, memory uses fewer tools")
        else:
            print("\n ~ NEUTRAL: No significant difference")
        return memory_success > 0
    else:
        print("\n ✗ MEMORY HURTS: Worse than baseline")
        return False


def main():
    parser = argparse.ArgumentParser(description="Memory Canary Tests")
    parser.add_argument(
        "test",
        choices=["layer1", "layer2", "layer3", "fair", "all"],
        help="Which test to run",
    )
    args = parser.parse_args()

    results = {}

    if args.test in ("layer1", "all"):
        results["layer1"] = test_layer1_context_block()
        print()

    if args.test in ("layer2", "all"):
        results["layer2"] = test_layer2_pattern_expand()
        print()

    if args.test in ("layer3", "all"):
        results["layer3"] = test_layer3_baseline_comparison()
        print()

    if args.test == "fair":
        results["fair"] = test_fair_comparison()
        print()

    if len(results) > 1:
        print("=" * 60)
        print(" SUMMARY")
        print("=" * 60)
        for layer, passed in results.items():
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {layer}: {status}")

        all_passed = all(results.values())
        print()
        if all_passed:
            print("All canary tests passed - plumbing works!")
        else:
            print("Some tests failed - fix before running effectiveness tests")


if __name__ == "__main__":
    main()
