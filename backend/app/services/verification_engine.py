"""Verification Engine - Auto-verification engine for acceptance criteria.

This module provides automatic verification of acceptance criteria by:
- Executing API criteria (curl commands with jq filters)
- Running test criteria (pytest commands)
- Taking screenshots for UI criteria (browser automation)
- Marking manual criteria as requiring human verification

Usage:
    verifier = VerificationEngine(project_id)
    result = await verifier.verify_criterion("FEAT-001", criterion_dict)
    results = await verifier.verify_feature("FEAT-001")
    summary = await verifier.verify_all_automatable()

Extracted from portfolio-ai/backend/app/services/criteria_verifier.py
Changes from source:
  - Renamed class CriteriaVerifier -> VerificationEngine
  - Added project_id to constructor and all methods
  - Uses get_connection() context manager
  - Fetches base_url from project config
  - Paths are project-configurable
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..logging_config import get_logger
from ..storage.connection import get_connection
from . import evidence_manager

logger = get_logger(__name__)

# Safety configuration
ALLOWED_URL_PATTERNS = [
    r"^http://localhost:\d+/api/",
    r"^http://127\.0\.0\.1:\d+/api/",
    r"^http://192\.168\.\d+\.\d+:\d+/",  # Local network
]

MAX_API_TIMEOUT = 30  # seconds
MAX_TEST_TIMEOUT = 60  # seconds
MAX_UI_TIMEOUT = 30  # seconds
MAX_CONCURRENT = 10  # parallel verifications
MAX_OUTPUT_LENGTH = 1000  # truncate output to this length

# Auto-verifiable types
AUTO_VERIFIABLE_TYPES = {"api", "test", "ui"}
MANUAL_ONLY_TYPES = {"backend", "quality", "db", "content"}


def get_project_config(project_id: str) -> dict[str, Any]:
    """Get project configuration from database.

    Args:
        project_id: Project ID

    Returns:
        Project config dict with base_url, backend_dir, browser_scripts_dir
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, base_url, backend_dir, browser_scripts_dir, data_dir
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            # Default config if project not found
            logger.warning("project_not_found", project_id=project_id)
            return {
                "name": "unknown",
                "base_url": "http://localhost:3000",
                "backend_dir": "/home/kasadis/summitflow/backend",
                "browser_scripts_dir": "/home/kasadis/summitflow/.claude/skills/browser-automation/scripts",
                "data_dir": f"/home/kasadis/summitflow/data/projects/{project_id}",
            }

        return {
            "name": row[0],
            "base_url": row[1] or "http://localhost:3000",
            "backend_dir": row[2] or "/home/kasadis/summitflow/backend",
            "browser_scripts_dir": row[3]
            or "/home/kasadis/summitflow/.claude/skills/browser-automation/scripts",
            "data_dir": row[4] or f"/home/kasadis/summitflow/data/projects/{project_id}",
        }


class VerificationEngine:
    """Auto-verification engine for acceptance criteria."""

    def __init__(self, project_id: str) -> None:
        """Initialize the verifier.

        Args:
            project_id: Project ID for scoping all operations
        """
        self.project_id = project_id
        self.config = get_project_config(project_id)

    async def verify_criterion(self, feature_id: str, criterion: dict[str, Any]) -> dict[str, Any]:
        """Verify a single criterion based on its type.

        Args:
            feature_id: The feature ID (e.g., FEAT-001)
            criterion: The criterion dict with id, criterion, verification, type, passed

        Returns:
            Updated criterion dict with passed, verified_at, verified_by, verification_output
        """
        criterion_type = criterion.get("type", "").lower()
        criterion_id = criterion.get("id", "unknown")

        start_time = time.time()
        logger.info(
            "verifying_criterion",
            project_id=self.project_id,
            feature_id=feature_id,
            criterion_id=criterion_id,
            type=criterion_type,
        )

        try:
            if criterion_type == "api":
                result = await self._verify_api_criterion(criterion)
            elif criterion_type == "test":
                result = await self._verify_test_criterion(criterion)
            elif criterion_type == "ui":
                result = await self._verify_ui_criterion(feature_id, criterion)
            elif criterion_type in MANUAL_ONLY_TYPES:
                result = self._handle_manual_criterion(criterion)
            else:
                result = {
                    **criterion,
                    "passed": None,
                    "verified_by": "unknown_type",
                    "verification_output": f"Unknown criterion type: {criterion_type}",
                }

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "criterion_verified",
                project_id=self.project_id,
                feature_id=feature_id,
                criterion_id=criterion_id,
                type=criterion_type,
                passed=result.get("passed"),
                duration_ms=duration_ms,
            )

            return result

        except Exception as e:
            logger.error(
                "criterion_verification_failed",
                project_id=self.project_id,
                feature_id=feature_id,
                criterion_id=criterion_id,
                error=str(e),
            )
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "error",
                "verification_output": f"Error: {str(e)[:MAX_OUTPUT_LENGTH]}",
            }

    async def verify_feature(self, feature_id: str) -> list[dict[str, Any]]:
        """Verify all criteria for a feature.

        Args:
            feature_id: The feature ID (e.g., FEAT-001)

        Returns:
            List of updated criterion dicts
        """
        # Get feature with criteria
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT acceptance_criteria
                FROM feature_capabilities
                WHERE project_id = %s AND feature_id = %s
                """,
                (self.project_id, feature_id),
            )
            row = cur.fetchone()

            if not row or not row[0]:
                logger.warning(
                    "no_criteria_found", project_id=self.project_id, feature_id=feature_id
                )
                return []

            criteria = row[0]

        # Verify each criterion
        results: list[dict[str, Any]] = []
        if not isinstance(criteria, list):
            logger.warning(
                "unexpected_criteria_type",
                project_id=self.project_id,
                feature_id=feature_id,
                type=type(criteria).__name__,
            )
            return []

        criteria_list: list[dict[str, Any]] = criteria
        for criterion in criteria_list:
            result = await self.verify_criterion(feature_id, criterion)
            results.append(result)

            # Save result immediately
            await self._save_criterion_result(feature_id, result)

        return results

    async def verify_all_automatable(
        self, type_filter: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """Verify all auto-verifiable criteria across all features in project.

        Args:
            type_filter: Optional type filter (api, test, ui)
            limit: Optional limit on number of criteria to verify

        Returns:
            Summary dict with counts and timing
        """
        start_time = time.time()

        # Get all features with criteria
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT feature_id, acceptance_criteria
                FROM feature_capabilities
                WHERE project_id = %s
                  AND acceptance_criteria IS NOT NULL
                  AND jsonb_array_length(acceptance_criteria) > 0
                ORDER BY feature_id
                """,
                (self.project_id,),
            )
            rows = cur.fetchall()

        # Collect all criteria to verify
        to_verify: list[tuple[str, dict[str, Any]]] = []
        for feature_id_val, criteria_val in rows:
            feature_id_str = str(feature_id_val) if feature_id_val else ""

            if not isinstance(criteria_val, list):
                logger.warning(
                    "unexpected_criteria_type",
                    project_id=self.project_id,
                    feature_id=feature_id_str,
                    type=type(criteria_val).__name__,
                )
                continue

            criteria_list: list[dict[str, Any]] = criteria_val
            for criterion in criteria_list:
                if not isinstance(criterion, dict):
                    continue
                ctype = str(criterion.get("type", "")).lower()
                if ctype not in AUTO_VERIFIABLE_TYPES:
                    continue
                if type_filter and ctype != type_filter:
                    continue
                to_verify.append((feature_id_str, criterion))

        if limit:
            to_verify = to_verify[:limit]

        logger.info(
            "starting_bulk_verification",
            project_id=self.project_id,
            total_criteria=len(to_verify),
            type_filter=type_filter,
        )

        # Verify with concurrency limit
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        results = {"passed": 0, "failed": 0, "errors": 0}

        async def verify_with_semaphore(feature_id: str, criterion: dict[str, Any]) -> None:
            async with semaphore:
                result = await self.verify_criterion(feature_id, criterion)
                await self._save_criterion_result(feature_id, result)

                if result.get("passed") is True:
                    results["passed"] += 1
                elif result.get("passed") is False:
                    results["failed"] += 1
                else:
                    results["errors"] += 1

        # Run all verifications
        tasks = [verify_with_semaphore(fid, c) for fid, c in to_verify]
        await asyncio.gather(*tasks, return_exceptions=True)

        duration = time.time() - start_time
        summary = {
            "project_id": self.project_id,
            "total_verified": len(to_verify),
            "passed": results["passed"],
            "failed": results["failed"],
            "errors": results["errors"],
            "duration_seconds": round(duration, 2),
            "type_filter": type_filter,
        }

        logger.info("bulk_verification_complete", **summary)
        return summary

    async def _verify_api_criterion(self, criterion: dict[str, Any]) -> dict[str, Any]:
        """Verify an API criterion by making HTTP request.

        Parses curl commands like:
            curl -s http://localhost:8000/api/health | jq '.status'
            curl -s -X POST http://localhost:8000/api/data -d '{"key": "value"}'
        """
        verification = criterion.get("verification", "")

        # Resolve any placeholders in the verification command
        verification = await self._resolve_api_placeholders(verification)

        # Parse the curl command (method, url, data, jq_filter)
        parsed = self._parse_curl_command_full(verification)

        if not parsed or not parsed.get("url"):
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "auto",
                "verification_output": f"Could not parse URL from: {verification}",
            }

        url = parsed["url"]
        method = parsed.get("method", "GET").upper()
        data = parsed.get("data")
        jq_filter = parsed.get("jq_filter")

        # Validate URL is allowed
        if not self._is_url_allowed(url):
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "auto",
                "verification_output": f"URL not allowed: {url}",
            }

        try:
            async with httpx.AsyncClient(timeout=MAX_API_TIMEOUT) as client:
                if method == "POST":
                    response = await client.post(url, json=data if data else None)
                elif method == "PATCH":
                    response = await client.patch(url, json=data if data else None)
                elif method == "PUT":
                    response = await client.put(url, json=data if data else None)
                elif method == "DELETE":
                    response = await client.delete(url)
                else:
                    response = await client.get(url)

            # Check HTTP status (allow 200, 201, 204)
            if response.status_code not in (200, 201, 204):
                return {
                    **criterion,
                    "passed": False,
                    "verified_at": datetime.now(UTC).isoformat(),
                    "verified_by": "auto",
                    "verification_output": f"HTTP {response.status_code}: {response.text[:200]}",
                }

            # Get response data
            try:
                response_data = response.json() if response.text else {}
            except json.JSONDecodeError:
                response_data = response.text[:MAX_OUTPUT_LENGTH]

            # Apply jq filter using real jq CLI if filter exists
            if jq_filter and isinstance(response_data, (dict, list)):
                output = await self._apply_jq_cli(response_data, jq_filter)
            else:
                output = response_data

            # Determine pass/fail
            passed = output is not None and output not in ("", [])

            return {
                **criterion,
                "passed": passed,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "auto",
                "verification_output": str(output)[:MAX_OUTPUT_LENGTH],
            }

        except httpx.TimeoutException:
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "auto",
                "verification_output": f"Timeout after {MAX_API_TIMEOUT}s",
            }
        except Exception as e:
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "auto",
                "verification_output": f"Error: {str(e)[:MAX_OUTPUT_LENGTH]}",
            }

    async def _verify_test_criterion(self, criterion: dict[str, Any]) -> dict[str, Any]:
        """Verify a test criterion by running pytest."""
        verification = criterion.get("verification", "")
        backend_dir = Path(self.config["backend_dir"])

        test_args = self._parse_pytest_command(verification)

        if not test_args:
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "pytest",
                "verification_output": f"Could not parse pytest command: {verification}",
            }

        test_path = test_args[0] if test_args else ""
        if not test_path.startswith("tests/"):
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "pytest",
                "verification_output": f"Test path must be under tests/: {test_path}",
            }

        try:
            proc = await asyncio.create_subprocess_exec(
                str(backend_dir / ".venv/bin/pytest"),
                *test_args,
                "-v",
                "--tb=short",
                cwd=str(backend_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=MAX_TEST_TIMEOUT
                )
            except TimeoutError:
                proc.kill()
                return {
                    **criterion,
                    "passed": False,
                    "verified_at": datetime.now(UTC).isoformat(),
                    "verified_by": "pytest",
                    "verification_output": f"Timeout after {MAX_TEST_TIMEOUT}s",
                }

            passed = proc.returncode == 0
            output = stdout.decode()[-MAX_OUTPUT_LENGTH:]

            return {
                **criterion,
                "passed": passed,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "pytest",
                "verification_output": output,
            }

        except Exception as e:
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "pytest",
                "verification_output": f"Error: {str(e)[:MAX_OUTPUT_LENGTH]}",
            }

    async def _verify_ui_criterion(
        self, feature_id: str, criterion: dict[str, Any]
    ) -> dict[str, Any]:
        """Capture evidence for UI criterion and queue for visual verification."""
        verification = criterion.get("verification", "")
        criterion_id = criterion.get("id", "unknown")
        base_url = self.config["base_url"]

        url_path = self._parse_screenshot_command(verification)

        if not url_path:
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "browser",
                "verification_output": f"Could not parse URL path: {verification}",
            }

        resolved_path = await self._resolve_url_placeholders(url_path)
        if not resolved_path:
            return {
                **criterion,
                "passed": None,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "manual_required",
                "verification_output": f"URL has unresolved placeholder: {url_path}. Requires manual verification.",
            }

        full_url = f"{base_url}{resolved_path}"

        try:
            result = await evidence_manager.capture_evidence(
                project_id=self.project_id,
                url=full_url,
                feature_id=feature_id,
                criterion_id=criterion_id,
            )

            if not result.get("success"):
                return {
                    **criterion,
                    "passed": False,
                    "verified_at": datetime.now(UTC).isoformat(),
                    "verified_by": "browser",
                    "verification_output": f"Evidence capture failed: {result.get('error', 'Unknown error')}",
                }

            version = result.get("version", 1)
            file_size = sum(f.get("size", 0) for f in result.get("files", []))
            evidence_data = result.get("evidence", {})

            evidence_manager.save_evidence(
                project_id=self.project_id,
                feature_id=feature_id,
                criterion_id=criterion_id,
                version=version,
                file_path=f"{feature_id}/{criterion_id}/v{version}",
                file_size_bytes=file_size,
                evidence_data=evidence_data,
            )

            # Auto-detect failures from evidence
            console_errors = evidence_data.get("console", {}).get("errorCount", 0)
            network_failures = evidence_data.get("network", {}).get("failedRequests", 0)
            page_state = evidence_data.get("pageState", {})
            has_content = page_state.get("hasContent", True)
            error_messages = page_state.get("keyElements", {}).get("errorMessages", 0)

            if network_failures > 0 or error_messages > 0 or not has_content:
                failure_reasons = []
                if network_failures > 0:
                    failures = evidence_data.get("network", {}).get("failures", [])
                    failure_reasons.append(f"{network_failures} network failures: {failures[:2]}")
                if error_messages > 0:
                    failure_reasons.append(f"{error_messages} error elements visible")
                if not has_content:
                    failure_reasons.append("Page has no content")

                return {
                    **criterion,
                    "passed": False,
                    "verified_at": datetime.now(UTC).isoformat(),
                    "verified_by": "auto",
                    "verification_output": f"Auto-failed: {'; '.join(failure_reasons)}. Evidence: {feature_id}/{criterion_id}/v{version}",
                }

            artifact_ref = f"{feature_id}/{criterion_id}/v{version}"
            text_sample = page_state.get("visibleTextSample", "")[:100]
            warning_note = f" ({console_errors} console errors)" if console_errors > 0 else ""

            return {
                **criterion,
                "passed": None,  # Requires visual verification
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "pending_visual_review",
                "verification_output": f"NEEDS_VISUAL_REVIEW: {artifact_ref} ({file_size} bytes){warning_note}. Preview: {text_sample}",
            }

        except Exception as e:
            return {
                **criterion,
                "passed": False,
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": "browser",
                "verification_output": f"Error: {str(e)[:MAX_OUTPUT_LENGTH]}",
            }

    def _handle_manual_criterion(self, criterion: dict[str, Any]) -> dict[str, Any]:
        """Mark a criterion as requiring manual verification."""
        ctype = criterion.get("type", "unknown")
        return {
            **criterion,
            "verified_by": "manual_required",
            "verification_output": f"Type '{ctype}' requires manual verification",
        }

    def _parse_curl_command_full(self, verification: str) -> dict[str, Any] | None:
        """Parse a curl command to extract method, URL, data, and jq filter."""
        result: dict[str, Any] = {"method": "GET"}

        shorthand_match = re.match(
            r"^(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s]+)", verification, re.IGNORECASE
        )
        if shorthand_match:
            result["method"] = shorthand_match.group(1).upper()
            result["url"] = f"http://localhost:8000{shorthand_match.group(2)}"
            return result

        method_match = re.search(r"-X\s+(GET|POST|PUT|PATCH|DELETE)", verification, re.IGNORECASE)
        if method_match:
            result["method"] = method_match.group(1).upper()

        url_match = re.search(r"http[s]?://[^\s|'\"]+", verification)
        if url_match:
            result["url"] = url_match.group(0)
        else:
            return None

        data_match = re.search(r"-d\s+['\"]([^'\"]+)['\"]", verification)
        if data_match:
            try:
                result["data"] = json.loads(data_match.group(1))
            except json.JSONDecodeError:
                result["data"] = data_match.group(1)

        jq_match = re.search(r"\|\s*jq\s+['\"]?(.+?)['\"]?\s*$", verification)
        if jq_match:
            result["jq_filter"] = jq_match.group(1).strip().strip("'\"")

        return result

    async def _apply_jq_cli(self, data: Any, jq_filter: str) -> Any:
        """Apply jq filter using the actual jq CLI."""
        if not jq_filter or jq_filter == ".":
            return data

        try:
            proc = await asyncio.create_subprocess_exec(
                "jq",
                "-c",
                jq_filter,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            input_data = json.dumps(data).encode()
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=input_data), timeout=5)

            if proc.returncode != 0:
                logger.warning(
                    "jq_filter_failed",
                    filter=jq_filter,
                    error=stderr.decode()[:200],
                )
                return self._apply_jq_filter_simple(data, jq_filter)

            output = stdout.decode().strip()
            if not output or output == "null":
                return None

            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return output

        except FileNotFoundError:
            logger.warning("jq_not_installed", fallback="simple_parser")
            return self._apply_jq_filter_simple(data, jq_filter)
        except TimeoutError:
            logger.warning("jq_timeout", filter=jq_filter)
            return None
        except Exception as e:
            logger.warning("jq_error", filter=jq_filter, error=str(e))
            return self._apply_jq_filter_simple(data, jq_filter)

    def _apply_jq_filter_simple(self, data: Any, jq_filter: str) -> Any:
        """Simple jq-like filter fallback."""
        if not jq_filter or jq_filter == ".":
            return data

        if jq_filter.startswith("{") and jq_filter.endswith("}"):
            inner = jq_filter[1:-1].strip()
            result = {}
            for part in inner.split(","):
                if ":" in part:
                    key, path = part.split(":", 1)
                    key = key.strip()
                    path = path.strip()
                    if path.startswith("."):
                        result[key] = self._apply_jq_filter_simple(data, path)
                    else:
                        result[key] = path
            return result

        if jq_filter.startswith("."):
            fields = jq_filter[1:].split(".")
            current = data
            for field in fields:
                if not field:
                    continue
                if isinstance(current, dict) and field in current:
                    current = current[field]
                elif isinstance(current, list) and field.isdigit():
                    idx = int(field)
                    if 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
                else:
                    return None
            return current

        return data

    def _parse_pytest_command(self, verification: str) -> list[str] | None:
        """Parse a pytest command to extract arguments."""
        cmd = verification.strip()
        if cmd.startswith("pytest "):
            cmd = cmd[7:]
        elif cmd.startswith("pytest"):
            cmd = cmd[6:]
        else:
            return None

        parts = []
        current = ""
        in_quotes = False
        for char in cmd:
            if char in {'"', "'"}:
                in_quotes = not in_quotes
            elif char == " " and not in_quotes:
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += char
        if current:
            parts.append(current)

        return parts if parts else None

    def _parse_screenshot_command(self, verification: str) -> str | None:
        """Parse a screenshot command or URL to extract URL path."""
        url_match = re.match(r"https?://[^/]+(/[^\s]*)?", verification.strip())
        if url_match:
            path = url_match.group(1) or "/"
            return path

        match = re.search(r"screenshot\s+(/[^\s]*)", verification, re.IGNORECASE)
        if match:
            path = match.group(1)
            return path if path else "/"
        return None

    async def _resolve_url_placeholders(self, url_path: str) -> str | None:
        """Resolve placeholders like {id}, {symbol} in URL paths."""
        if "{" not in url_path:
            return url_path

        # TODO: Add project-specific placeholder resolution
        # For now, return None for unresolved placeholders
        logger.warning(
            "unresolved_url_placeholder", project_id=self.project_id, url_path=url_path
        )
        return None

    async def _resolve_api_placeholders(self, verification: str) -> str:
        """Resolve placeholders in API verification commands."""
        if "{" not in verification:
            return verification

        # TODO: Add project-specific placeholder resolution
        return verification

    def _is_url_allowed(self, url: str) -> bool:
        """Check if URL matches allowed patterns."""
        return any(re.match(pattern, url) for pattern in ALLOWED_URL_PATTERNS)

    async def _save_criterion_result(self, feature_id: str, result: dict[str, Any]) -> bool:
        """Save verification result to database."""
        criterion_id = result.get("id")
        if not criterion_id:
            return False

        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE feature_capabilities
                    SET acceptance_criteria = (
                        SELECT jsonb_agg(
                            CASE
                                WHEN c->>'id' = %s THEN
                                    c || jsonb_build_object(
                                        'passed', %s::boolean,
                                        'verified_at', %s,
                                        'verified_by', %s,
                                        'verification_output', %s
                                    )
                                ELSE c
                            END
                        )
                        FROM jsonb_array_elements(acceptance_criteria) c
                    ),
                    updated_at = NOW()
                    WHERE project_id = %s AND feature_id = %s
                    """,
                    (
                        criterion_id,
                        result.get("passed"),
                        result.get("verified_at"),
                        result.get("verified_by"),
                        result.get("verification_output"),
                        self.project_id,
                        feature_id,
                    ),
                )
                conn.commit()
                return True

        except Exception as e:
            logger.error(
                "save_criterion_result_failed",
                project_id=self.project_id,
                feature_id=feature_id,
                criterion_id=criterion_id,
                error=str(e),
            )
            return False
