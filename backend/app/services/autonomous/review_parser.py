"""Review response parser for Opus code reviews.

Parses and validates review responses, extracting structured
feedback from JSON-formatted output.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


def parse_review_response(response_text: str) -> dict[str, Any]:
    """Parse the review response from Opus.

    Extracts JSON from response text and validates required fields.
    Falls back to REQUEST_FIX verdict if parsing fails.

    Args:
        response_text: Raw response text from reviewer

    Returns:
        Parsed review dict with verdict, summary, issues, suggestions, confidence
    """
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r"\{[^{}]*\"verdict\"[^{}]*\}", response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.warning("review_parse_failed", response_preview=response_text[:200])
            return {
                "verdict": "REQUEST_FIX",
                "summary": "Could not parse review response - requesting manual review",
                "issues": ["Review response was not in expected format"],
                "suggestions": [],
                "confidence": 0.0,
                "raw_response": response_text,
            }

    try:
        parsed: dict[str, Any] = json.loads(json_str)
        if parsed.get("verdict") not in ("APPROVE", "REJECT", "REQUEST_FIX"):
            parsed["verdict"] = "REQUEST_FIX"
            parsed.setdefault("issues", []).append("Invalid verdict in response")

        parsed.setdefault("summary", "No summary provided")
        parsed.setdefault("issues", [])
        parsed.setdefault("suggestions", [])
        parsed.setdefault("confidence", 0.5)

        return parsed
    except json.JSONDecodeError as e:
        logger.warning("review_json_decode_failed", error=str(e))
        return {
            "verdict": "REQUEST_FIX",
            "summary": f"JSON parse error: {e}",
            "issues": ["Could not parse review JSON"],
            "suggestions": [],
            "confidence": 0.0,
            "raw_response": response_text,
        }
