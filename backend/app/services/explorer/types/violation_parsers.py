"""Output parsers for code violation detection tools (jscpd, vulture, semgrep)."""

from __future__ import annotations

import json

from ....logging_config import get_logger
from .violation_models import CodeViolation, ViolationType

logger = get_logger(__name__)


def parse_jscpd_output(output: str) -> list[CodeViolation]:
    """Parse jscpd JSON output into violations."""
    violations: list[CodeViolation] = []

    try:
        data = json.loads(output)
        duplicates = data.get("duplicates", [])

        for dup in duplicates:
            first_file = dup.get("firstFile", {})
            second_file = dup.get("secondFile", {})

            first_path = first_file.get("name", "")
            second_path = second_file.get("name", "")
            lines = dup.get("lines", 0)
            tokens = dup.get("tokens", 0)

            if lines < 5:
                continue

            violations.append(
                CodeViolation(
                    violation_type=ViolationType.DUPLICATE_UTILITY,
                    file_path=first_path,
                    detail=f"Duplicate code: {lines} lines, {tokens} tokens shared with {second_path}",
                    severity="warning",
                    line_start=first_file.get("start"),
                    line_end=first_file.get("end"),
                    related_files=[second_path],
                )
            )

    except json.JSONDecodeError:
        logger.debug("Failed to parse jscpd JSON output")
    except Exception as e:
        logger.warning(f"Error parsing jscpd output: {e}")

    return violations


def parse_vulture_line(line: str) -> CodeViolation | None:
    """Parse a single vulture output line.

    Format: path/to/file.py:123: unused function 'foo' (90% confidence)
    """
    try:
        if ":" not in line:
            return None

        parts = line.split(":", 2)
        if len(parts) < 3:
            return None

        file_path = parts[0]
        line_num = int(parts[1]) if parts[1].isdigit() else None
        detail = parts[2].strip()

        if "unused" not in detail.lower():
            return None

        return CodeViolation(
            violation_type=ViolationType.MISSING_INFRASTRUCTURE,
            file_path=file_path,
            detail=f"Dead code: {detail}",
            severity="warning",
            line_start=line_num,
        )

    except Exception:
        logger.debug("Failed to parse vulture output line", exc_info=True)
        return None


def parse_semgrep_output(output: str) -> list[CodeViolation]:
    """Parse semgrep JSON output into violations."""
    violations: list[CodeViolation] = []

    try:
        data = json.loads(output)
        results = data.get("results", [])

        for result in results:
            path = result.get("path", "")
            start = result.get("start", {})
            end = result.get("end", {})
            message = result.get("extra", {}).get("message", "Missing infrastructure pattern")
            severity = result.get("extra", {}).get("severity", "WARNING").lower()

            violations.append(
                CodeViolation(
                    violation_type=ViolationType.MISSING_INFRASTRUCTURE,
                    file_path=path,
                    detail=message,
                    severity="error" if severity == "error" else "warning",
                    line_start=start.get("line"),
                    line_end=end.get("line"),
                )
            )

    except json.JSONDecodeError:
        logger.debug("Failed to parse semgrep JSON output")
    except Exception as e:
        logger.warning(f"Error parsing semgrep output: {e}")

    return violations
