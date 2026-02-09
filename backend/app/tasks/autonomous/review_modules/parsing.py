"""Review response parsing."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_review_response(content: str) -> dict[str, Any]:
    """Parse the reviewer agent's response.

    Args:
        content: Raw response from reviewer agent

    Returns:
        Parsed review result with verdict and details
    """
    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            return parsed
    except json.JSONDecodeError:
        pass

    content_upper = content.upper()
    if "APPROVED" in content_upper:
        return {"verdict": "APPROVED", "summary": content}
    if "PLAN_DEFECT" in content_upper:
        return {"verdict": "PLAN_DEFECT", "summary": content}
    if "ESCALATE" in content_upper:
        return {"verdict": "ESCALATE", "summary": content}
    return {"verdict": "NEEDS_FIX", "summary": content}
