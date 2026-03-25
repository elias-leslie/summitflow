"""Detection logic for code violations (jscpd, vulture, semgrep, built-in).

Each function runs one external tool or pattern scan and returns a list of
``CodeViolation`` objects.  ``CodeViolationDetector`` in ``code_violations.py``
orchestrates these functions; they are kept here to keep the class small.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ....logging_config import get_logger
from .code_violations import CodeViolation, ViolationType
from .violation_parsers import parse_jscpd_output, parse_semgrep_output, parse_vulture_line

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants shared across detectors
# ---------------------------------------------------------------------------

JSCPD_MIN_TOKENS: int = 10
JSCPD_MIN_COPIES: int = 2
VULTURE_MIN_CONFIDENCE: int = 80

EXCLUDE_PATTERNS: list[str] = [
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

VULTURE_EXCLUDE: str = ".venv,__pycache__,.git,node_modules,.next,dist,build"


# ---------------------------------------------------------------------------
# jscpd duplicate detection
# ---------------------------------------------------------------------------


def detect_duplicates(project_root: Path, backend_dir: str) -> list[CodeViolation]:
    """Detect code duplication using jscpd across backend and frontend dirs."""
    scan_dirs = [
        (project_root / backend_dir / "app", ["python"]),
        (project_root / "frontend" / "components", ["typescript", "tsx"]),
        (project_root / "frontend" / "lib", ["typescript", "tsx"]),
    ]
    violations: list[CodeViolation] = []
    for scan_dir, formats in scan_dirs:
        if scan_dir.exists():
            violations.extend(_run_jscpd(project_root, scan_dir, formats))
    return violations


def _run_jscpd(project_root: Path, scan_dir: Path, formats: list[str]) -> list[CodeViolation]:
    """Run jscpd on a single directory and return violations."""
    format_args = [arg for fmt in formats for arg in ("--format", fmt)]
    ignore_args = [arg for pat in EXCLUDE_PATTERNS for arg in ("--ignore", pat)]

    cmd = [
        "jscpd", str(scan_dir),
        "--min-tokens", str(JSCPD_MIN_TOKENS),
        "--threshold", str(JSCPD_MIN_COPIES),
        "--reporters", "json",
        "--output", "/dev/stdout",
        "--silent",
        *format_args,
        *ignore_args,
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=project_root
        )
        return parse_jscpd_output(proc.stdout) if proc.stdout else []
    except FileNotFoundError:
        logger.debug("jscpd not available, skipping duplicate detection")
    except subprocess.TimeoutExpired:
        logger.warning("jscpd timed out scanning %s", scan_dir)
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("jscpd failed for %s: %s", scan_dir, e)
    return []


# ---------------------------------------------------------------------------
# vulture dead-code detection
# ---------------------------------------------------------------------------


def detect_dead_code(project_root: Path, backend_dir: str) -> list[CodeViolation]:
    """Detect dead/unused Python code using vulture."""
    backend_path = project_root / backend_dir
    if not backend_path.exists():
        return []

    cmd = [
        "vulture", str(backend_path / "app"),
        "--min-confidence", str(VULTURE_MIN_CONFIDENCE),
        "--exclude", VULTURE_EXCLUDE,
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, cwd=project_root
        )
        return [
            v for line in proc.stdout.splitlines()
            if (v := parse_vulture_line(line)) is not None
        ]
    except FileNotFoundError:
        logger.debug("vulture not available, skipping dead code detection")
    except subprocess.TimeoutExpired:
        logger.warning("vulture timed out")
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("vulture failed: %s", e)
    return []


# ---------------------------------------------------------------------------
# semgrep / built-in missing-infrastructure detection
# ---------------------------------------------------------------------------


def detect_missing_infrastructure(
    project_root: Path, backend_dir: str, semgrep_rules_dir: Path
) -> list[CodeViolation]:
    """Detect missing infrastructure patterns using semgrep (or built-in fallback)."""
    if not semgrep_rules_dir.exists():
        logger.debug("No .semgrep directory found, using built-in patterns")
        return detect_missing_infrastructure_builtin(project_root, backend_dir)

    cmd = [
        "semgrep",
        "--config", str(semgrep_rules_dir),
        "--json", "--quiet",
        str(project_root / backend_dir),
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, cwd=project_root
        )
        return parse_semgrep_output(proc.stdout) if proc.stdout else []
    except FileNotFoundError:
        logger.debug("semgrep not available, using built-in patterns")
        return detect_missing_infrastructure_builtin(project_root, backend_dir)
    except subprocess.TimeoutExpired:
        logger.warning("semgrep timed out")
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("semgrep failed: %s", e)
    return []


def detect_missing_infrastructure_builtin(
    project_root: Path, backend_dir: str
) -> list[CodeViolation]:
    """Fallback detection using built-in patterns when semgrep is unavailable."""
    api_dir = project_root / backend_dir / "app" / "api"
    if not api_dir.exists():
        return []
    return [v for py_file in api_dir.rglob("*.py") for v in _check_api_patterns(py_file)]


def _check_api_patterns(file_path: Path) -> list[CodeViolation]:
    """Check a Python API file for missing logging instrumentation."""
    try:
        content = file_path.read_text()
        if not ("@router." in content or "@app." in content):
            return []
        if "logger." in content or "logging." in content:
            return []
        return [
            CodeViolation(
                violation_type=ViolationType.MISSING_INFRASTRUCTURE,
                file_path=str(file_path),
                detail="API endpoint file missing logging instrumentation",
                severity="warning",
            )
        ]
    except Exception as e:
        logger.debug("Failed to check API patterns in %s: %s", file_path, e)
        return []


# ---------------------------------------------------------------------------
# Parallel-implementation helpers
# ---------------------------------------------------------------------------


def find_pattern_implementations(
    pattern_name: str, search_paths: list[Path]
) -> list[tuple[Path, int]]:
    """Scan search_paths for Python files containing pattern_name."""
    implementations: list[tuple[Path, int]] = []
    for search_path in search_paths:
        if not search_path.exists():
            continue
        for py_file in search_path.rglob("*.py"):
            line_num = _first_matching_line(py_file, pattern_name)
            if line_num is not None:
                implementations.append((py_file, line_num))
    return implementations


def _first_matching_line(py_file: Path, pattern: str) -> int | None:
    """Return the 1-based line number of the first case-insensitive match, or None."""
    try:
        for i, line in enumerate(py_file.read_text().splitlines(), 1):
            if pattern.lower() in line.lower():
                return i
    except Exception:
        logger.debug(
            "Failed to read file for parallel implementation scan: %s", py_file, exc_info=True
        )
    return None
