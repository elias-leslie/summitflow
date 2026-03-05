"""Review response parsing."""

from __future__ import annotations

import json
import re
from typing import Any


def _strip_tool_call_artifacts(content: str) -> str:
    """Remove tool call/result artifacts that LLMs occasionally hallucinate.

    Strips:
    - <tool_call>...</tool_call> blocks
    - <tool_result>...</tool_result> blocks
    - {"type": "tool_use", ...} JSON objects
    """
    # Strip XML-style tool call/result blocks
    cleaned = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", content)
    cleaned = re.sub(r"<tool_result>[\s\S]*?</tool_result>", "", cleaned)

    # Strip {"type": "tool_use", ...} JSON objects — match balanced braces
    # Use a pattern that targets the tool_use type marker specifically
    cleaned = re.sub(
        r'\{\s*"type"\s*:\s*"tool_use"[^}]*(?:\{[^}]*\}[^}]*)?\}',
        "",
        cleaned,
    )

    return cleaned.strip()


def parse_review_response(content: str) -> dict[str, Any]:
    """Parse the reviewer agent's response.

    Multi-strategy extractor that handles hallucinated tool call artifacts:
    1. Strip tool_use/tool_call blocks from the content
    2. Search for a flat JSON object containing a "verdict" key
    3. Try fenced code block extraction
    4. Try parsing nested JSON and walking into "input"/"result" subkeys
    5. Keyword-based text fallback (APPROVED/PLAN_DEFECT/ESCALATE)
    6. Default to NEEDS_FIX only when truly nothing parseable

    Args:
        content: Raw response from reviewer agent

    Returns:
        Parsed review result with verdict and details
    """
    # Strategy 1: Strip tool call artifacts and search for verdict JSON
    cleaned = _strip_tool_call_artifacts(content)

    # Strategy 2: Flat pattern — JSON object with a "verdict" key (no nesting)
    verdict_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', cleaned, re.DOTALL)
    if verdict_match:
        try:
            parsed: dict[str, Any] = json.loads(verdict_match.group())
            if "verdict" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # Strategy 3: Fenced code block
    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if "verdict" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # Strategy 4: Any JSON object in cleaned content — walk subkeys for verdict
    for json_match in re.finditer(r"\{[\s\S]*?\}", cleaned):
        try:
            parsed = json.loads(json_match.group())
            if "verdict" in parsed:
                return parsed
            # Check common wrapper subkeys
            for subkey in ("input", "result", "output", "content"):
                sub = parsed.get(subkey)
                if isinstance(sub, dict) and "verdict" in sub:
                    return sub
                if isinstance(sub, str):
                    try:
                        inner = json.loads(sub)
                        if isinstance(inner, dict) and "verdict" in inner:
                            return inner
                    except json.JSONDecodeError:
                        pass
        except json.JSONDecodeError:
            continue

    # Strategy 5: Try parsing the original (unstripped) content with greedy match
    # in case stripping was too aggressive
    try:
        greedy_match = re.search(r"\{[\s\S]*\}", content)
        if greedy_match:
            parsed = json.loads(greedy_match.group())
            if "verdict" in parsed:
                return parsed
    except json.JSONDecodeError:
        pass

    # Strategy 6: Keyword-based text fallback
    content_upper = content.upper()
    if "APPROVED" in content_upper:
        return {"verdict": "APPROVED", "summary": content}
    if "PLAN_DEFECT" in content_upper:
        return {"verdict": "PLAN_DEFECT", "summary": content}
    if "ESCALATE" in content_upper:
        return {"verdict": "ESCALATE", "summary": content}

    # Default: nothing parseable
    return {"verdict": "NEEDS_FIX", "summary": content}
