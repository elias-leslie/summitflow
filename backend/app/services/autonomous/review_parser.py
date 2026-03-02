"""Review response parser for Opus code reviews.

Parses and validates review responses, extracting structured
feedback from JSON-formatted output.
"""

from __future__ import annotations

import json
import re

from ...logging_config import get_logger
from .review_types import ReviewResult

logger = get_logger(__name__)

_VALID_VERDICTS = ("APPROVE", "REJECT", "REQUEST_FIX")


def _fallback_result(summary: str, issues: list[str], raw_response: str) -> ReviewResult:
    """Return a REQUEST_FIX result used when parsing fails."""
    return ReviewResult(
        verdict="REQUEST_FIX",
        summary=summary,
        issues=issues,
        suggestions=[],
        confidence=0.0,
        raw_response=raw_response,
    )


def _extract_json_str(response_text: str) -> str | None:
    """Extract a JSON string from a raw response.

    Tries a fenced code-block pattern first, then a bare object pattern.
    Returns None when no JSON can be found.
    """
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        return json_match.group(1)

    json_match = re.search(r"\{[^{}]*\"verdict\"[^{}]*\}", response_text, re.DOTALL)
    if json_match:
        return json_match.group(0)

    return None


def _build_review_result(parsed: dict) -> ReviewResult:
    """Validate and normalise a parsed review dict into a ReviewResult."""
    if parsed.get("verdict") not in _VALID_VERDICTS:
        parsed["verdict"] = "REQUEST_FIX"
        parsed.setdefault("issues", []).append("Invalid verdict in response")

    parsed.setdefault("summary", "No summary provided")
    parsed.setdefault("issues", [])
    parsed.setdefault("suggestions", [])
    parsed.setdefault("confidence", 0.5)

    return ReviewResult(
        verdict=parsed["verdict"],
        summary=parsed["summary"],
        issues=parsed["issues"],
        suggestions=parsed["suggestions"],
        confidence=parsed["confidence"],
    )


def parse_review_response(response_text: str) -> ReviewResult:
    """Parse the review response from Opus.

    Extracts JSON from response text and validates required fields.
    Falls back to REQUEST_FIX verdict if parsing fails.

    Args:
        response_text: Raw response text from reviewer

    Returns:
        Parsed review dict with verdict, summary, issues, suggestions, confidence
    """
    json_str = _extract_json_str(response_text)
    if json_str is None:
        logger.warning("review_parse_failed", response_preview=response_text[:200])
        return _fallback_result(
            summary="Could not parse review response - requesting manual review",
            issues=["Review response was not in expected format"],
            raw_response=response_text,
        )

    try:
        parsed = json.loads(json_str)
        return _build_review_result(parsed)
    except json.JSONDecodeError as e:
        logger.warning("review_json_decode_failed", error=str(e))
        return _fallback_result(
            summary=f"JSON parse error: {e}",
            issues=["Could not parse review JSON"],
            raw_response=response_text,
        )
