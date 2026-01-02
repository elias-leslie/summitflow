"""Fast-path extraction for common observation patterns.

Bypasses LLM for patterns that can be reliably detected with regex.
Target: 50%+ of observations extracted without LLM calls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Track fast-path metrics
_fast_path_hits = 0
_fast_path_misses = 0


@dataclass
class FastPathResult:
    """Result from fast-path extraction."""

    matched: bool
    observation_type: str = ""
    title: str = ""
    concepts: list[str] | None = None
    priority: str = "medium"
    confidence: float = 0.85  # Fast-path has high confidence for matched patterns
    entities: list[dict[str, str]] | None = None
    narrative: str | None = None
    facts: dict[str, Any] | None = None
    files_modified: list[str] | None = None
    files_read: list[str] | None = None


# Error patterns
ERROR_PATTERNS = [
    (re.compile(r"(Error|Exception|FAILED|Traceback)", re.IGNORECASE), "high"),
    (re.compile(r"(error\[|ERROR:)", re.IGNORECASE), "high"),
    (
        re.compile(r"(TypeError|ValueError|ImportError|KeyError|AttributeError)", re.IGNORECASE),
        "high",
    ),
    (re.compile(r"(FATAL|CRITICAL|panic)", re.IGNORECASE), "high"),
]

# Git commit pattern
GIT_COMMIT_PATTERN = re.compile(r"^\[[\w\-/]+\s+([a-f0-9]{7,})\]\s+(.+?)$", re.MULTILINE)

# File write success patterns
FILE_SUCCESS_PATTERNS = [
    re.compile(r"File (written|created|saved) successfully", re.IGNORECASE),
    re.compile(r"has been updated", re.IGNORECASE),
    re.compile(r"changes applied", re.IGNORECASE),
]

# Test result patterns
PYTEST_PATTERN = re.compile(
    r"(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+skipped)?", re.IGNORECASE
)

VITEST_PATTERN = re.compile(r"Tests?\s+(\d+)\s+passed(?:\s*\|\s*(\d+)\s+failed)?", re.IGNORECASE)

# File path extractor
FILE_PATH_PATTERN = re.compile(r'["\']?(/[a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)["\']?')


def extract_file_paths(text: str) -> list[str]:
    """Extract file paths from text."""
    matches = FILE_PATH_PATTERN.findall(text)
    # Deduplicate and limit
    seen: set[str] = set()
    result: list[str] = []
    for path in matches:
        if path not in seen and len(result) < 5:
            seen.add(path)
            result.append(path)
    return result


def fast_path_extract(
    tool_name: str,
    tool_input: dict[str, Any] | None,
    tool_output: str | None,
) -> FastPathResult:
    """Attempt fast-path extraction without LLM.

    Returns FastPathResult with matched=True if pattern detected,
    otherwise matched=False (caller should use LLM).

    Args:
        tool_name: Name of the tool executed
        tool_input: Tool input parameters
        tool_output: Tool output/result

    Returns:
        FastPathResult with extracted observation or matched=False
    """
    global _fast_path_hits, _fast_path_misses

    output = tool_output or ""
    input_data = tool_input or {}

    # 1. Check for errors (highest priority)
    for pattern, priority in ERROR_PATTERNS:
        if pattern.search(output):
            # Extract error type if possible
            error_match = re.search(
                r"(TypeError|ValueError|ImportError|KeyError|AttributeError|"
                r"RuntimeError|FileNotFoundError|PermissionError|ConnectionError|"
                r"AssertionError|ModuleNotFoundError)",
                output,
            )
            error_type = error_match.group(1) if error_match else "Error"

            # Extract first line of error for title
            lines = output.strip().split("\n")
            error_line = next(
                (ln for ln in lines if any(p[0].search(ln) for p in ERROR_PATTERNS)),
                lines[0] if lines else "Error occurred",
            )
            title = error_line[:80].strip()
            if len(error_line) > 80:
                title += "..."

            entities = [{"type": "error_type", "value": error_type}]
            files = extract_file_paths(output)
            if files:
                entities.extend([{"type": "file", "value": f} for f in files[:3]])

            _fast_path_hits += 1
            logger.debug(f"fast_path_hit: error pattern detected: {error_type}")

            return FastPathResult(
                matched=True,
                observation_type="error",
                title=f"{error_type}: {title[:60]}",
                concepts=["debugging"],
                priority=priority,
                confidence=0.95,
                entities=entities,
                narrative=f"Tool {tool_name} encountered {error_type}. Check output for details.",
                files_read=files[:3] if files else None,
            )

    # 2. Check for file write/edit success
    if tool_name in ("Write", "Edit"):
        for pattern in FILE_SUCCESS_PATTERNS:
            if pattern.search(output):
                file_path = input_data.get("file_path", input_data.get("file", "unknown"))

                _fast_path_hits += 1
                logger.debug(f"fast_path_hit: file write success: {file_path}")

                return FastPathResult(
                    matched=True,
                    observation_type="operational",
                    title=f"Modified: {file_path.split('/')[-1]}",
                    concepts=["code_patterns"],
                    priority="low",
                    confidence=0.90,
                    entities=[{"type": "file", "value": file_path}],
                    narrative=f"Successfully modified {file_path}.",
                    files_modified=[file_path],
                )

    # 3. Check for git commit
    if tool_name == "Bash" and "git commit" in str(input_data):
        match = GIT_COMMIT_PATTERN.search(output)
        if match:
            commit_hash = match.group(1)
            commit_msg = match.group(2)[:60]

            _fast_path_hits += 1
            logger.debug(f"fast_path_hit: git commit: {commit_hash}")

            return FastPathResult(
                matched=True,
                observation_type="operational",
                title=f"Committed: {commit_msg}",
                concepts=["code_patterns"],
                priority="medium",
                confidence=0.95,
                entities=[{"type": "tool", "value": "git"}],
                narrative=f"Git commit {commit_hash}: {commit_msg}",
                facts={"commit_hash": commit_hash, "message": commit_msg},
            )

    # 4. Check for test results
    if tool_name == "Bash":
        # Check pytest
        pytest_match = PYTEST_PATTERN.search(output)
        if pytest_match:
            passed = int(pytest_match.group(1))
            failed = int(pytest_match.group(2)) if pytest_match.group(2) else 0
            skipped = int(pytest_match.group(3)) if pytest_match.group(3) else 0

            _fast_path_hits += 1
            status = "passed" if failed == 0 else "failed"
            logger.debug(f"fast_path_hit: pytest {status}: {passed} passed, {failed} failed")

            return FastPathResult(
                matched=True,
                observation_type="operational",
                title=f"Tests {status}: {passed} passed, {failed} failed",
                concepts=["testing"],
                priority="high" if failed > 0 else "low",
                confidence=0.95,
                entities=[{"type": "tool", "value": "pytest"}],
                narrative=f"Test run completed: {passed} passed, {failed} failed, {skipped} skipped.",
                facts={"passed": passed, "failed": failed, "skipped": skipped},
            )

        # Check vitest/jest
        vitest_match = VITEST_PATTERN.search(output)
        if vitest_match:
            passed = int(vitest_match.group(1))
            failed = int(vitest_match.group(2)) if vitest_match.group(2) else 0

            _fast_path_hits += 1
            status = "passed" if failed == 0 else "failed"
            logger.debug(f"fast_path_hit: vitest/jest {status}")

            return FastPathResult(
                matched=True,
                observation_type="operational",
                title=f"Tests {status}: {passed} passed, {failed} failed",
                concepts=["testing"],
                priority="high" if failed > 0 else "low",
                confidence=0.95,
                entities=[{"type": "tool", "value": "vitest"}],
                narrative=f"Test run completed: {passed} passed, {failed} failed.",
                facts={"passed": passed, "failed": failed},
            )

    # No fast-path match
    _fast_path_misses += 1
    return FastPathResult(matched=False)


def get_fast_path_metrics() -> dict[str, int | float]:
    """Get fast-path extraction metrics.

    Returns:
        Dict with hits, misses, total (int), and hit_rate (float)
    """
    total = _fast_path_hits + _fast_path_misses
    hit_rate = (_fast_path_hits / total * 100) if total > 0 else 0.0

    return {
        "fast_path_hits": _fast_path_hits,
        "fast_path_misses": _fast_path_misses,
        "fast_path_total": total,
        "fast_path_hit_rate": round(hit_rate, 1),
    }


def reset_fast_path_metrics() -> None:
    """Reset fast-path metrics (for testing)."""
    global _fast_path_hits, _fast_path_misses
    _fast_path_hits = 0
    _fast_path_misses = 0
