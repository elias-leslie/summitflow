"""Evidence validator for Agent Hub worker output.

Validates evidence contracts against schema and verifies actual changes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from ..logging_config import get_logger

logger = get_logger(__name__)

EVIDENCE_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "tasks/autocode-orchestration/evidence-schema.json"
)
_evidence_schema: dict[str, Any] | None = None


def _load_evidence_schema() -> dict[str, Any]:
    """Load and cache the evidence schema."""
    global _evidence_schema
    if _evidence_schema is None:
        with open(EVIDENCE_SCHEMA_PATH) as f:
            _evidence_schema = json.load(f)
    assert _evidence_schema is not None
    return _evidence_schema


@dataclass
class ValidationResult:
    """Result of evidence validation."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        """Add an error and mark as failed."""
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        """Add a warning without failing validation."""
        self.warnings.append(msg)


def validate_schema(evidence: dict[str, Any]) -> ValidationResult:
    """Validate evidence against JSON schema.

    Args:
        evidence: Evidence contract dictionary

    Returns:
        ValidationResult with schema validation outcome
    """
    result = ValidationResult(passed=True)

    try:
        schema = _load_evidence_schema()
        jsonschema.validate(evidence, schema)
        result.details["schema"] = "valid"
    except jsonschema.ValidationError as e:
        result.add_error(f"Schema validation failed: {e.message}")
        result.details["schema"] = "invalid"
        result.details["schema_path"] = list(e.absolute_path)
    except FileNotFoundError:
        result.add_warning(f"Schema not found at {EVIDENCE_SCHEMA_PATH}")
        result.details["schema"] = "skipped"
    except Exception as e:
        result.add_error(f"Schema validation error: {e}")
        result.details["schema"] = "error"

    return result


def validate_git_diff(
    evidence: dict[str, Any],
    actual_diff: str,
) -> ValidationResult:
    """Validate git diff hash matches evidence.

    Args:
        evidence: Evidence contract dictionary
        actual_diff: Current git diff output

    Returns:
        ValidationResult with diff validation outcome
    """
    result = ValidationResult(passed=True)

    evidence_data = evidence.get("evidence", {})
    expected_hash = evidence_data.get("git_diff_hash")

    if not expected_hash:
        result.add_warning("No git_diff_hash in evidence")
        result.details["diff_validation"] = "skipped"
        return result

    actual_hash = hashlib.sha256(actual_diff.encode()).hexdigest()

    if expected_hash == actual_hash:
        result.details["diff_validation"] = "matched"
        result.details["diff_hash"] = actual_hash
    else:
        result.add_error(
            f"Git diff hash mismatch: expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
        )
        result.details["diff_validation"] = "mismatch"
        result.details["expected_hash"] = expected_hash
        result.details["actual_hash"] = actual_hash

    return result


def validate_files_modified(
    evidence: dict[str, Any],
    repo_path: Path | None = None,
) -> ValidationResult:
    """Validate that claimed files were actually modified.

    Args:
        evidence: Evidence contract dictionary
        repo_path: Repository path to check files (defaults to cwd)

    Returns:
        ValidationResult with file validation outcome
    """
    result = ValidationResult(passed=True)
    repo = repo_path or Path.cwd()

    evidence_data = evidence.get("evidence", {})
    files_modified = evidence_data.get("files_modified", [])

    if not files_modified:
        if evidence.get("status") == "completed":
            result.add_error("Completed evidence has no files_modified")
        else:
            result.details["files_validation"] = "skipped"
        return result

    # Get actual git status
    try:
        git_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if git_result.returncode != 0:
            result.add_warning(f"git status failed: {git_result.stderr}")
            result.details["files_validation"] = "git_error"
            return result

        # Parse git status output
        git_files: set[str] = set()
        for line in git_result.stdout.strip().split("\n"):
            if line:
                # Format: "XY path" where X=index, Y=worktree
                status_file = line[3:].strip()
                # Handle renamed files: "old -> new"
                if " -> " in status_file:
                    status_file = status_file.split(" -> ")[1]
                git_files.add(status_file)

    except subprocess.TimeoutExpired:
        result.add_warning("git status timed out")
        result.details["files_validation"] = "timeout"
        return result
    except Exception as e:
        result.add_warning(f"git status error: {e}")
        result.details["files_validation"] = "error"
        return result

    # Check each claimed file
    missing_in_git: list[str] = []
    verified: list[str] = []

    for file_path in files_modified:
        if file_path in git_files:
            verified.append(file_path)
        else:
            # Also check if file exists (might already be committed)
            full_path = repo / file_path
            if full_path.exists():
                verified.append(file_path)
            else:
                missing_in_git.append(file_path)

    result.details["files_claimed"] = files_modified
    result.details["files_verified"] = verified
    result.details["files_missing"] = missing_in_git

    if missing_in_git:
        result.add_error(f"Files claimed but not found: {', '.join(missing_in_git)}")
        result.details["files_validation"] = "mismatch"
    else:
        result.details["files_validation"] = "verified"

    return result


def validate_evidence(
    evidence: dict[str, Any],
    repo_path: Path | None = None,
    actual_diff: str | None = None,
) -> ValidationResult:
    """Full evidence validation: schema + diff + files.

    Args:
        evidence: Evidence contract dictionary
        repo_path: Repository path for file checks
        actual_diff: Current git diff (fetched if not provided)

    Returns:
        Combined ValidationResult
    """
    result = ValidationResult(passed=True)

    # Schema validation
    schema_result = validate_schema(evidence)
    result.errors.extend(schema_result.errors)
    result.warnings.extend(schema_result.warnings)
    result.details["schema"] = schema_result.details.get("schema")

    # File validation
    files_result = validate_files_modified(evidence, repo_path)
    result.errors.extend(files_result.errors)
    result.warnings.extend(files_result.warnings)
    result.details["files"] = files_result.details

    # Git diff validation
    if actual_diff is None and repo_path:
        try:
            git_diff_proc = subprocess.run(
                ["git", "diff"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            actual_diff = git_diff_proc.stdout
        except Exception as e:
            result.add_warning(f"Could not get git diff: {e}")
            actual_diff = ""

    if actual_diff is not None:
        diff_validation_result = validate_git_diff(evidence, actual_diff)
        result.errors.extend(diff_validation_result.errors)
        result.warnings.extend(diff_validation_result.warnings)
        result.details["diff"] = diff_validation_result.details

    # Final pass/fail
    if result.errors:
        result.passed = False

    return result
