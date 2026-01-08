"""Regression detection service for evidence comparison.

Three-layer detection:
1. Pixel diff (visual comparison)
2. Console errors (JavaScript errors)
3. AI analysis (semantic comparison)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import numpy as np
from PIL import Image

from ...constants import CLAUDE_HAIKU, CLAUDE_OPUS
from ...storage import evidence_config, evidence_regressions

logger = logging.getLogger(__name__)

# Default pixel diff threshold (5%)
DEFAULT_PIXEL_THRESHOLD = 0.05


@dataclass
class RegressionResult:
    """Result of regression detection."""

    has_regression: bool
    regression_type: str | None = None
    pixel_diff_pct: float | None = None
    console_errors_added: int = 0
    ai_analysis: dict[str, Any] | None = None
    severity: str = "unknown"
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def no_regression(cls) -> RegressionResult:
        return cls(has_regression=False)


def pixel_diff(
    baseline_path: str | Path,
    current_path: str | Path,
    *,
    threshold: float = DEFAULT_PIXEL_THRESHOLD,
) -> tuple[float, bool]:
    """Compare two images and return pixel difference percentage.

    Uses Pillow and numpy for comparison. Returns the percentage of
    pixels that differ beyond a tolerance.

    Args:
        baseline_path: Path to baseline image
        current_path: Path to current image
        threshold: Regression threshold (0.0-1.0)

    Returns:
        Tuple of (diff_percentage, is_regression)
    """
    baseline_path = Path(baseline_path)
    current_path = Path(current_path)

    if not baseline_path.exists():
        logger.warning(f"Baseline not found: {baseline_path}")
        return 0.0, False

    if not current_path.exists():
        logger.warning(f"Current image not found: {current_path}")
        return 0.0, False

    try:
        baseline = Image.open(baseline_path).convert("RGBA")
        current = Image.open(current_path).convert("RGBA")

        # Resize if dimensions differ
        if baseline.size != current.size:
            current = current.resize(baseline.size, Image.Resampling.LANCZOS)

        # Convert to numpy arrays
        baseline_arr = np.array(baseline, dtype=np.int16)
        current_arr = np.array(current, dtype=np.int16)

        # Calculate per-pixel difference
        diff = np.abs(baseline_arr - current_arr)

        # Count significantly different pixels (diff > tolerance per channel)
        tolerance = 10  # Allow minor color variations
        significant_diff = np.any(diff > tolerance, axis=2)
        diff_count = np.sum(significant_diff)
        total_pixels = baseline.width * baseline.height

        diff_pct = diff_count / total_pixels
        is_regression = diff_pct > threshold

        return float(diff_pct), is_regression

    except Exception as e:
        logger.exception(f"Error comparing images: {e}")
        return 0.0, False


def detect_console_regression(
    baseline_console: list[dict[str, Any]],
    current_console: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """Detect new console errors that weren't in baseline.

    Args:
        baseline_console: Console entries from baseline capture
        current_console: Console entries from current capture

    Returns:
        Tuple of (count of new errors, list of new error messages)
    """
    # Extract error messages from baseline
    baseline_errors = {
        entry.get("text", "")
        for entry in baseline_console
        if entry.get("type") in ("error", "exception")
    }

    # Find new errors
    new_errors = []
    for entry in current_console:
        if entry.get("type") in ("error", "exception"):
            text = entry.get("text", "")
            if text and text not in baseline_errors:
                new_errors.append(text)

    return len(new_errors), new_errors


def detect_regression(
    project_id: str,
    evidence_id: int,
    baseline_evidence_id: int | None,
    current_data: dict[str, Any],
    baseline_data: dict[str, Any] | None = None,
) -> RegressionResult:
    """Perform full regression detection on evidence.

    Runs through all three detection layers:
    1. Pixel diff (if screenshots available)
    2. Console error comparison
    3. AI analysis (if enabled in project config)

    Args:
        project_id: Project ID for config lookup
        evidence_id: Current evidence ID
        baseline_evidence_id: Baseline evidence ID (if any)
        current_data: Current evidence metadata
        baseline_data: Baseline evidence metadata (if any)

    Returns:
        RegressionResult with detection details
    """
    config = evidence_config.get_config(project_id)
    threshold = config.get("regression_threshold", DEFAULT_PIXEL_THRESHOLD)

    result = RegressionResult(has_regression=False)
    result.details["layers_checked"] = []

    # Layer 1: Pixel diff
    current_path = current_data.get("file_path")
    baseline_path = baseline_data.get("file_path") if baseline_data else None

    if current_path and baseline_path:
        diff_pct, is_regression = pixel_diff(baseline_path, current_path, threshold=threshold)
        result.pixel_diff_pct = diff_pct
        result.details["layers_checked"].append("pixel")
        result.details["pixel"] = {
            "diff_pct": diff_pct,
            "threshold": threshold,
            "is_regression": is_regression,
        }

        if is_regression:
            result.has_regression = True
            result.regression_type = "visual"
            result.severity = _calculate_severity(diff_pct)

    # Layer 2: Console errors
    current_console = current_data.get("console", [])
    baseline_console = baseline_data.get("console", []) if baseline_data else []

    if current_console:
        new_error_count, new_errors = detect_console_regression(
            baseline_console,
            current_console,
        )
        result.console_errors_added = new_error_count
        result.details["layers_checked"].append("console")
        result.details["console"] = {
            "new_errors": new_error_count,
            "error_messages": new_errors[:5],  # Limit stored messages
        }

        if new_error_count > 0 and not result.has_regression:
            result.has_regression = True
            result.regression_type = "console"
            result.severity = "high" if new_error_count >= 3 else "medium"

    # Layer 3: AI analysis (if enabled and pixel regression detected)
    # Only call AI for visual regressions to optimize costs
    if (
        config.get("ai_review_enabled", False)
        and result.regression_type == "visual"
        and current_path
        and baseline_path
        and result.pixel_diff_pct is not None
    ):
        result.details["layers_checked"].append("ai")
        # Note: This is a sync function, caller should use asyncio.run() or similar
        # For now, we'll skip the async call and note it should be called separately
        result.details["ai_analysis_pending"] = True

    return result


async def detect_regression_async(
    project_id: str,
    evidence_id: int,
    baseline_evidence_id: int | None,
    current_data: dict[str, Any],
    baseline_data: dict[str, Any] | None = None,
) -> RegressionResult:
    """Async version of detect_regression that includes AI analysis.

    Use this version when AI analysis is enabled and you can await.
    """
    # First run the sync detection
    result = detect_regression(
        project_id=project_id,
        evidence_id=evidence_id,
        baseline_evidence_id=baseline_evidence_id,
        current_data=current_data,
        baseline_data=baseline_data,
    )

    # If AI analysis is pending, run it now
    if result.details.get("ai_analysis_pending"):
        config = evidence_config.get_config(project_id)
        current_path = current_data.get("file_path")
        baseline_path = baseline_data.get("file_path") if baseline_data else None

        if current_path and baseline_path and result.pixel_diff_pct is not None:
            ai_result = await ai_analyze_regression(
                baseline_path=baseline_path,
                current_path=current_path,
                diff_pct=result.pixel_diff_pct,
                use_opus=config.get("ai_model") == "opus",
            )

            result.ai_analysis = ai_result
            result.details["ai"] = ai_result

            # AI can override regression decision if it determines change is intentional
            if ai_result.get("likely_intentional") and ai_result.get("is_regression") is False:
                result.has_regression = False
                result.details["ai_override"] = True

            del result.details["ai_analysis_pending"]

    return result


def _calculate_severity(diff_pct: float) -> str:
    """Calculate severity based on pixel diff percentage."""
    if diff_pct >= 0.3:  # 30%+
        return "critical"
    elif diff_pct >= 0.15:  # 15%+
        return "high"
    elif diff_pct >= 0.05:  # 5%+
        return "medium"
    else:
        return "low"


async def ai_analyze_regression(
    baseline_path: str | Path,
    current_path: str | Path,
    diff_pct: float,
    *,
    use_opus: bool = False,
) -> dict[str, Any]:
    """Use Claude Vision to analyze visual regression semantically.

    Only called when pixel_diff > threshold to optimize costs.

    Args:
        baseline_path: Path to baseline screenshot
        current_path: Path to current screenshot
        diff_pct: Pixel diff percentage for context
        use_opus: Use CLAUDE_OPUS instead of CLAUDE_HAIKU for deeper analysis

    Returns:
        Dict with is_regression, description, severity, and recommendations
    """
    baseline_path = Path(baseline_path)
    current_path = Path(current_path)

    if not baseline_path.exists() or not current_path.exists():
        return {
            "is_regression": False,
            "description": "Missing images for analysis",
            "severity": "unknown",
            "error": "images_not_found",
        }

    # Read images as base64
    import base64
    import json

    with open(baseline_path, "rb") as f:
        baseline_b64 = base64.standard_b64encode(f.read()).decode("utf-8")
    with open(current_path, "rb") as f:
        current_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    # Select model based on config
    model = CLAUDE_OPUS if use_opus else CLAUDE_HAIKU

    prompt = f"""Compare these two UI screenshots for visual regression testing.

Baseline (first image) vs Current (second image).
Pixel difference: {diff_pct * 100:.1f}%

Analyze for:
1. Is this a meaningful regression or acceptable variation?
2. What specifically changed (layout, colors, content, elements)?
3. Severity assessment (critical, high, medium, low)
4. Is this likely intentional (new feature) or unintentional (bug)?

Respond in JSON format:
{{
  "is_regression": true/false,
  "description": "Brief description of changes",
  "severity": "critical|high|medium|low",
  "change_type": "layout|style|content|removed|added|broken",
  "likely_intentional": true/false,
  "recommendations": ["action1", "action2"]
}}"""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": baseline_b64,
                            },
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": current_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        # Parse JSON response
        first_block = response.content[0]
        if not hasattr(first_block, "text"):
            return {
                "is_regression": False,
                "description": "AI returned non-text response",
                "severity": "unknown",
                "error": "unexpected_response_type",
            }
        response_text = first_block.text
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result: dict[str, Any] = json.loads(response_text.strip())
        result["model_used"] = model
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI response: {e}")
        return {
            "is_regression": True,  # Assume regression on parse failure
            "description": "AI analysis returned non-JSON response",
            "severity": "medium",
            "error": "parse_error",
        }
    except Exception as e:
        logger.exception(f"AI analysis error: {e}")
        return {
            "is_regression": False,
            "description": f"AI analysis failed: {e}",
            "severity": "unknown",
            "error": str(e),
        }


async def record_regression(
    evidence_id: int,
    baseline_evidence_id: int | None,
    result: RegressionResult,
) -> int | None:
    """Record a detected regression in the database.

    Args:
        evidence_id: Current evidence ID
        baseline_evidence_id: Baseline evidence ID
        result: Regression detection result

    Returns:
        Regression record ID if created, None otherwise
    """
    if not result.has_regression:
        return None

    try:
        regression = evidence_regressions.insert_regression(
            evidence_id=evidence_id,
            regression_type=result.regression_type or "unknown",
            baseline_evidence_id=baseline_evidence_id,
            pixel_diff_pct=result.pixel_diff_pct,
            console_errors_added=result.console_errors_added,
            ai_analysis=result.ai_analysis,
            severity=result.severity,
        )
        return regression.get("id")
    except Exception as e:
        logger.exception(f"Error recording regression: {e}")
        return None
