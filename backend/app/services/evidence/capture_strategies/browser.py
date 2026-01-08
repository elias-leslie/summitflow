"""Browser capture strategy for web pages."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .base import CaptureConfig, CaptureStrategy, EvidenceResult, EvidenceType, ExplorerEntry

# Default timeout for browser operations
CAPTURE_TIMEOUT_SECONDS = 60

# Default viewport configurations
DEFAULT_VIEWPORTS = [
    {"name": "desktop", "width": 1280, "height": 720},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 390, "height": 844},
]


def get_browser_scripts_dir() -> Path:
    """Get browser scripts directory."""
    return Path(os.path.expanduser("~/.claude/skills/browser-automation/scripts"))


class BrowserCapture(CaptureStrategy):
    """Capture strategy for browser-based evidence (screenshots, console, performance)."""

    @property
    def name(self) -> str:
        return "Browser Capture"

    def supports_entry_type(self, entry_type: str) -> bool:
        return entry_type == "page"

    def get_evidence_types(self) -> list[EvidenceType]:
        return ["screenshot", "console_log", "performance", "accessibility"]

    async def capture(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> list[EvidenceResult]:
        """Capture browser evidence for a page entry.

        Captures screenshots at multiple viewports and extracts console/performance data.
        """
        results: list[EvidenceResult] = []
        viewports = config.get("viewports", DEFAULT_VIEWPORTS)
        url = self._build_url(entry)

        if not url:
            return [EvidenceResult.failure("screenshot", "Could not determine URL for entry")]

        # Capture screenshot for each viewport
        for viewport in viewports:
            result = await self._capture_viewport(
                url=url,
                viewport=viewport,
                entry=entry,
                config=config,
            )
            results.append(result)

        return results

    async def _capture_viewport(
        self,
        url: str,
        viewport: dict[str, Any],
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> EvidenceResult:
        """Capture evidence at a specific viewport."""
        scripts_dir = get_browser_scripts_dir()
        script_path = scripts_dir / "capture-evidence.js"

        if not script_path.exists():
            return EvidenceResult.failure(
                "screenshot",
                f"Capture script not found: {script_path}",
            )

        # Build output path based on entry and viewport
        viewport_name = viewport.get("name", "default")
        width = viewport.get("width", 1280)
        height = viewport.get("height", 720)

        try:
            # Call the capture-evidence.js script with viewport args
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(script_path),
                url,
                "--width",
                str(width),
                "--height",
                str(height),
                "--json",  # Request JSON output
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            timeout = config.get("timeout_ms", CAPTURE_TIMEOUT_SECONDS * 1000) / 1000
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            output = stdout.decode()
            error_output = stderr.decode()

            # Parse JSON result from script
            result_data = self._parse_capture_output(output)

            if result_data.get("success"):
                return EvidenceResult(
                    success=True,
                    evidence_type="screenshot",
                    file_path=result_data.get("file_path"),
                    file_size_bytes=result_data.get("file_size_bytes"),
                    metadata={
                        "viewport": viewport_name,
                        "width": width,
                        "height": height,
                        "url": url,
                        "console_errors": result_data.get("console_errors", []),
                        "console_warnings": result_data.get("console_warnings", []),
                        "performance": result_data.get("performance", {}),
                    },
                    console_errors=len(result_data.get("console_errors", [])),
                    console_warnings=len(result_data.get("console_warnings", [])),
                    duration_ms=result_data.get("duration_ms", 0),
                )

            return EvidenceResult.failure(
                "screenshot",
                result_data.get("error", f"Unknown error: {error_output[:200]}"),
            )

        except TimeoutError:
            timeout_sec = config.get("timeout_ms", CAPTURE_TIMEOUT_SECONDS * 1000) / 1000
            return EvidenceResult.failure(
                "screenshot",
                f"Capture timed out after {timeout_sec}s",
            )
        except Exception as e:
            return EvidenceResult.failure("screenshot", str(e))

    def _build_url(self, entry: ExplorerEntry) -> str | None:
        """Build URL from explorer entry."""
        path = entry.get("path", "")
        if not path:
            return None

        # If path is already a full URL, return it
        if path.startswith(("http://", "https://")):
            return path

        # Otherwise, build from project config
        # For now, assume local development URL
        metadata = entry.get("metadata", {})
        port = metadata.get("port", 3000)
        base_url = metadata.get("base_url", f"http://localhost:{port}")

        return f"{base_url}{path}"

    def _parse_capture_output(self, output: str) -> dict[str, Any]:
        """Parse JSON output from capture script."""
        # Look for JSON line in output
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{") and '"success"' in line:
                try:
                    parsed: dict[str, Any] = json.loads(line)
                    return parsed
                except json.JSONDecodeError:
                    continue

        # Try parsing entire output as JSON
        try:
            parsed_full: dict[str, Any] = json.loads(output)
            return parsed_full
        except json.JSONDecodeError:
            return {"success": False, "error": f"Could not parse output: {output[:200]}"}


async def capture_single_screenshot(
    url: str,
    output_path: str,
    *,
    width: int = 1280,
    height: int = 720,
    full_page: bool = True,
) -> EvidenceResult:
    """Convenience function to capture a single screenshot.

    Args:
        url: URL to capture
        output_path: Path to save screenshot
        width: Viewport width
        height: Viewport height
        full_page: Whether to capture full page

    Returns:
        EvidenceResult with capture status
    """
    scripts_dir = get_browser_scripts_dir()
    script_path = scripts_dir / "screenshot.js"

    if not script_path.exists():
        return EvidenceResult.failure(
            "screenshot",
            f"Screenshot script not found: {script_path}",
        )

    try:
        args = [
            "node",
            str(script_path),
            url,
            output_path,
        ]
        if full_page:
            args.append("--full-page")

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "VIEWPORT_WIDTH": str(width), "VIEWPORT_HEIGHT": str(height)},
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )

        if proc.returncode == 0:
            file_size = Path(output_path).stat().st_size if Path(output_path).exists() else None
            return EvidenceResult(
                success=True,
                evidence_type="screenshot",
                file_path=output_path,
                file_size_bytes=file_size,
                metadata={"url": url, "width": width, "height": height},
            )

        return EvidenceResult.failure(
            "screenshot",
            f"Screenshot failed: {stderr.decode()[:200]}",
        )

    except TimeoutError:
        return EvidenceResult.failure(
            "screenshot",
            f"Screenshot timed out after {CAPTURE_TIMEOUT_SECONDS}s",
        )
    except Exception as e:
        return EvidenceResult.failure("screenshot", str(e))
