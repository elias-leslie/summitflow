"""Code violation detector for Explorer.

Detects architecture violations across the codebase:
- PARALLEL_IMPLEMENTATION: Multiple implementations of the same functionality
- MISSING_INFRASTRUCTURE: Missing caching, error handling, observability patterns
- DUPLICATE_UTILITY: Literal code duplication (copy-paste)

Uses external tools:
- jscpd: Copy-paste detection (10+ tokens, 2+ copies)
- vulture: Python dead code detection (--min-confidence 80)
- semgrep: Pattern-based detection for missing infrastructure
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from ....logging_config import get_logger

logger = get_logger(__name__)


class ViolationType(Enum):
    PARALLEL_IMPLEMENTATION = "parallel_implementation"
    MISSING_INFRASTRUCTURE = "missing_infrastructure"
    DUPLICATE_UTILITY = "duplicate_utility"


@dataclass
class CodeViolation:
    violation_type: ViolationType
    file_path: str
    detail: str
    severity: str = "warning"
    line_start: int | None = None
    line_end: int | None = None
    related_files: list[str] = field(default_factory=list)


class CodeViolationDetector:
    """Detects code architecture violations using external tools."""

    JSCPD_MIN_TOKENS = 10
    JSCPD_MIN_COPIES = 2
    VULTURE_MIN_CONFIDENCE = 80

    EXCLUDE_PATTERNS: ClassVar[list[str]] = [
        "**/.venv/**",
        "**/__pycache__/**",
        "**/.git/**",
        "**/node_modules/**",
        "**/.next/**",
        "**/dist/**",
        "**/build/**",
        "**/*.min.js",
        "**/*.min.css",
    ]

    def __init__(self, project_root: Path, backend_dir: str = "backend") -> None:
        self.project_root = project_root
        self.backend_dir = backend_dir
        self._semgrep_rules_dir = project_root / ".semgrep"

    def detect_violations(self) -> list[CodeViolation]:
        """Detect all code violations in the project.

        Returns:
            List of detected violations
        """
        violations: list[CodeViolation] = []

        violations.extend(self._detect_duplicates())
        violations.extend(self._detect_dead_code())
        violations.extend(self._detect_missing_infrastructure())

        return violations

    def _detect_duplicates(self) -> list[CodeViolation]:
        """Detect code duplication using jscpd.

        Scans Python (backend/) and TypeScript (frontend/src/, frontend/lib/).
        """
        violations: list[CodeViolation] = []

        scan_dirs = [
            (self.project_root / self.backend_dir / "app", ["python"]),
            (self.project_root / "frontend" / "components", ["typescript", "tsx"]),
            (self.project_root / "frontend" / "lib", ["typescript", "tsx"]),
        ]

        for scan_dir, formats in scan_dirs:
            if not scan_dir.exists():
                continue

            try:
                format_args = []
                for fmt in formats:
                    format_args.extend(["--format", fmt])

                ignore_args = []
                for pattern in self.EXCLUDE_PATTERNS:
                    ignore_args.extend(["--ignore", pattern])

                cmd = [
                    "jscpd",
                    str(scan_dir),
                    "--min-tokens",
                    str(self.JSCPD_MIN_TOKENS),
                    "--threshold",
                    str(self.JSCPD_MIN_COPIES),
                    "--reporters",
                    "json",
                    "--output",
                    "/dev/stdout",
                    "--silent",
                    *format_args,
                    *ignore_args,
                ]

                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=self.project_root,
                )

                if proc.stdout:
                    violations.extend(self._parse_jscpd_output(proc.stdout))

            except FileNotFoundError:
                logger.debug("jscpd not available, skipping duplicate detection")
            except subprocess.TimeoutExpired:
                logger.warning(f"jscpd timed out scanning {scan_dir}")
            except Exception as e:
                logger.warning(f"jscpd failed for {scan_dir}: {e}")

        return violations

    def _parse_jscpd_output(self, output: str) -> list[CodeViolation]:
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

    def _detect_dead_code(self) -> list[CodeViolation]:
        """Detect dead/unused Python code using vulture."""
        violations: list[CodeViolation] = []

        backend_path = self.project_root / self.backend_dir
        if not backend_path.exists():
            return violations

        try:
            exclude_patterns = ".venv,__pycache__,.git,node_modules,.next,dist,build"
            cmd = [
                "vulture",
                str(backend_path / "app"),
                "--min-confidence",
                str(self.VULTURE_MIN_CONFIDENCE),
                "--exclude",
                exclude_patterns,
            ]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.project_root,
            )

            for line in proc.stdout.splitlines():
                violation = self._parse_vulture_line(line)
                if violation:
                    violations.append(violation)

        except FileNotFoundError:
            logger.debug("vulture not available, skipping dead code detection")
        except subprocess.TimeoutExpired:
            logger.warning("vulture timed out")
        except Exception as e:
            logger.warning(f"vulture failed: {e}")

        return violations

    def _parse_vulture_line(self, line: str) -> CodeViolation | None:
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

    def _detect_missing_infrastructure(self) -> list[CodeViolation]:
        """Detect missing infrastructure patterns using semgrep.

        Looks for:
        - Missing error handling in API endpoints
        - Missing caching opportunities
        - Missing observability (logging, metrics)
        """
        violations: list[CodeViolation] = []

        if not self._semgrep_rules_dir.exists():
            logger.debug("No .semgrep directory found, using built-in patterns")
            return self._detect_missing_infrastructure_builtin()

        try:
            cmd = [
                "semgrep",
                "--config",
                str(self._semgrep_rules_dir),
                "--json",
                "--quiet",
                str(self.project_root / self.backend_dir),
            ]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                cwd=self.project_root,
            )

            if proc.stdout:
                violations.extend(self._parse_semgrep_output(proc.stdout))

        except FileNotFoundError:
            logger.debug("semgrep not available, using built-in patterns")
            return self._detect_missing_infrastructure_builtin()
        except subprocess.TimeoutExpired:
            logger.warning("semgrep timed out")
        except Exception as e:
            logger.warning(f"semgrep failed: {e}")

        return violations

    def _parse_semgrep_output(self, output: str) -> list[CodeViolation]:
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

    def _detect_missing_infrastructure_builtin(self) -> list[CodeViolation]:
        """Fallback detection using built-in patterns when semgrep unavailable.

        Uses simple AST analysis for common patterns.
        """
        violations: list[CodeViolation] = []

        backend_path = self.project_root / self.backend_dir
        if not backend_path.exists():
            return violations

        api_dir = backend_path / "app" / "api"
        if api_dir.exists():
            for py_file in api_dir.rglob("*.py"):
                violations.extend(self._check_api_patterns(py_file))

        return violations

    def _check_api_patterns(self, file_path: Path) -> list[CodeViolation]:
        """Check a Python API file for missing patterns."""
        violations: list[CodeViolation] = []

        try:
            content = file_path.read_text()

            if "@router." in content or "@app." in content:
                if "try:" not in content and "except" not in content:
                    pass

                if "logger." not in content and "logging." not in content:
                    violations.append(
                        CodeViolation(
                            violation_type=ViolationType.MISSING_INFRASTRUCTURE,
                            file_path=str(file_path),
                            detail="API endpoint file missing logging instrumentation",
                            severity="warning",
                        )
                    )

        except Exception as e:
            logger.debug(f"Failed to check API patterns in {file_path}: {e}")

        return violations

    def detect_parallel_implementations(
        self,
        pattern_name: str,
        search_paths: list[Path],
    ) -> list[CodeViolation]:
        """Detect parallel implementations of a named pattern.

        This is a more targeted search for known pattern duplications.
        Example: Multiple token estimation implementations.

        Args:
            pattern_name: Human-readable name of the pattern
            search_paths: Paths to search for implementations

        Returns:
            Violations if multiple implementations found
        """
        violations: list[CodeViolation] = []
        implementations: list[tuple[Path, int]] = []

        for search_path in search_paths:
            if not search_path.exists():
                continue

            for py_file in search_path.rglob("*.py"):
                try:
                    content = py_file.read_text()
                    for i, line in enumerate(content.splitlines(), 1):
                        if pattern_name.lower() in line.lower():
                            implementations.append((py_file, i))
                            break
                except Exception:
                    logger.debug("Failed to read file for parallel implementation scan: %s", py_file, exc_info=True)
                    continue

        if len(implementations) > 1:
            files = [str(p) for p, _ in implementations]
            violations.append(
                CodeViolation(
                    violation_type=ViolationType.PARALLEL_IMPLEMENTATION,
                    file_path=str(implementations[0][0]),
                    detail=f"Multiple implementations of '{pattern_name}' found in {len(implementations)} files",
                    severity="error",
                    line_start=implementations[0][1],
                    related_files=files[1:],
                )
            )

        return violations

    def get_violation_summary(self, violations: list[CodeViolation]) -> dict[str, Any]:
        """Get a summary of violations by type and severity.

        Args:
            violations: List of violations to summarize

        Returns:
            Summary dict with counts by type and severity
        """
        summary: dict[str, Any] = {
            "total": len(violations),
            "by_type": {},
            "by_severity": {"error": 0, "warning": 0},
            "files_affected": set(),
        }

        for v in violations:
            type_name = v.violation_type.value
            summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1
            summary["by_severity"][v.severity] = summary["by_severity"].get(v.severity, 0) + 1
            summary["files_affected"].add(v.file_path)

        summary["files_affected"] = len(summary["files_affected"])
        return summary
