"""File scanning logic for code health checks."""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from ...services.code_health.classifier import Finding
from ...services.explorer.types.file_detection import detect_compat_cruft, detect_magic_strings
from ...storage import code_health_lists

logger = get_logger(__name__)


def scan_project_files(
    project_id: str,
    root_path: str,
    backend_dir: str = "backend",
) -> tuple[list[Finding], int, int]:
    """Scan project files for code health issues.

    Args:
        project_id: Project to scan
        root_path: Root path of the project
        backend_dir: Backend directory name (default: "backend")

    Returns:
        Tuple of (findings, scanned_files_count, skipped_files_count)
    """
    findings: list[Finding] = []
    scanned_files = 0
    skipped_files = 0

    scan_dir = Path(root_path) / backend_dir / "app"

    if not scan_dir.exists():
        scan_dir = Path(root_path) / "app"

    for py_file in scan_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            rel_path = str(py_file.relative_to(root_path))

            # Check for compat cruft
            compat_cruft = detect_compat_cruft(rel_path, content)
            for category, count in (compat_cruft or {}).items():
                # Check if pattern is in allow list
                pattern = f"{category}:{rel_path}"
                if code_health_lists.is_pattern_allowed(project_id, category, pattern):
                    skipped_files += 1
                    continue

                findings.append(
                    Finding(
                        file_path=rel_path,
                        category=category,
                        pattern=f"{count} instances",
                        context=extract_context(content, category),
                    )
                )

            # Check for magic strings
            magic_strings = detect_magic_strings(rel_path, content)
            for category, count in (magic_strings or {}).items():
                pattern = f"{category}:{rel_path}"
                if code_health_lists.is_pattern_allowed(project_id, category, pattern):
                    skipped_files += 1
                    continue

                findings.append(
                    Finding(
                        file_path=rel_path,
                        category=f"magic_string:{category}",
                        pattern=f"{count} instances",
                        context=extract_context(content, category),
                    )
                )

            scanned_files += 1

        except Exception as e:
            logger.warning(f"Failed to scan {py_file}: {e}")

    logger.info(
        f"scan_project_files: scanned {scanned_files} files, found {len(findings)} findings"
    )

    return findings, scanned_files, skipped_files


def extract_context(content: str, category: str) -> str:
    """Extract relevant context from file content for classification."""
    # Return first 500 chars as context
    return content[:500] if content else ""
