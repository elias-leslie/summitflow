"""HTTP capture strategy for API endpoints."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import CaptureConfig, CaptureStrategy, EvidenceResult, EvidenceType, ExplorerEntry

# Default timeout for HTTP requests
DEFAULT_TIMEOUT_SECONDS = 30

# Maximum body size to store (100KB)
MAX_BODY_SIZE = 102400


class HttpCapture(CaptureStrategy):
    """Capture strategy for HTTP API endpoints."""

    @property
    def name(self) -> str:
        return "HTTP Capture"

    def supports_entry_type(self, entry_type: str) -> bool:
        return entry_type == "endpoint"

    def get_evidence_types(self) -> list[EvidenceType]:
        return ["api_response"]

    async def capture(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> list[EvidenceResult]:
        """Capture HTTP response for an API endpoint."""
        url = self._build_url(entry)

        if not url:
            return [EvidenceResult.failure("api_response", "Could not determine URL for entry")]

        result = await self._capture_response(url, entry, config)
        return [result]

    async def _capture_response(
        self,
        url: str,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> EvidenceResult:
        """Capture HTTP response with timing and metadata."""
        timeout_sec = config.get("timeout_ms", DEFAULT_TIMEOUT_SECONDS * 1000) / 1000
        auth_headers = config.get("auth_headers", {})
        method = entry.get("metadata", {}).get("method", "GET")

        start_time = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=auth_headers,
                )

                duration_ms = int((time.perf_counter() - start_time) * 1000)

                # Truncate body if too large
                body = response.text
                body_truncated = len(body) > MAX_BODY_SIZE
                if body_truncated:
                    body = body[:MAX_BODY_SIZE] + "\n... [truncated]"

                # Try to parse as JSON for structured response
                try:
                    body_json: dict[str, Any] | list[Any] | None = response.json()
                except Exception:
                    body_json = None

                return EvidenceResult(
                    success=True,
                    evidence_type="api_response",
                    metadata={
                        "url": url,
                        "method": method,
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": body,
                        "body_json": body_json,
                        "body_truncated": body_truncated,
                        "content_type": response.headers.get("content-type"),
                        "latency_ms": duration_ms,
                    },
                    duration_ms=duration_ms,
                )

        except httpx.TimeoutException:
            return EvidenceResult.failure(
                "api_response",
                f"Request timed out after {timeout_sec}s",
            )
        except httpx.ConnectError as e:
            return EvidenceResult.failure(
                "api_response",
                f"Connection failed: {e}",
            )
        except Exception as e:
            return EvidenceResult.failure("api_response", str(e))

    def _build_url(self, entry: ExplorerEntry) -> str | None:
        """Build URL from explorer entry."""
        path = entry.get("path", "")
        if not path:
            return None

        # If path is already a full URL, return it
        if path.startswith(("http://", "https://")):
            return path

        # Build from project config
        metadata = entry.get("metadata", {})
        port = metadata.get("port", 8000)
        base_url = metadata.get("base_url", f"http://localhost:{port}")

        return f"{base_url}{path}"


async def capture_api_endpoint(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | dict[str, Any] | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SECONDS,
) -> EvidenceResult:
    """Convenience function to capture a single API endpoint.

    Args:
        url: Full URL to request
        method: HTTP method
        headers: Request headers
        body: Request body (string or dict for JSON)
        timeout_sec: Request timeout

    Returns:
        EvidenceResult with response data
    """
    start_time = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            # Prepare request body
            json_body = None
            content = None
            if body is not None:
                if isinstance(body, dict):
                    json_body = body
                else:
                    content = body

            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                content=content,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Truncate response if too large
            response_body = response.text
            body_truncated = len(response_body) > MAX_BODY_SIZE
            if body_truncated:
                response_body = response_body[:MAX_BODY_SIZE] + "\n... [truncated]"

            return EvidenceResult(
                success=True,
                evidence_type="api_response",
                metadata={
                    "url": url,
                    "method": method,
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response_body,
                    "body_truncated": body_truncated,
                    "latency_ms": duration_ms,
                },
                duration_ms=duration_ms,
            )

    except httpx.TimeoutException:
        return EvidenceResult.failure(
            "api_response",
            f"Request timed out after {timeout_sec}s",
        )
    except Exception as e:
        return EvidenceResult.failure("api_response", str(e))
