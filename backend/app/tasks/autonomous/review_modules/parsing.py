"""Review response parsing."""

from __future__ import annotations

import json
import re
from typing import Any


def _extract_balanced_braces(text: str, start: int) -> str | None:
    """Extract a balanced JSON object starting at the given '{' position.

    Returns the substring from the opening '{' to its matching '}',
    correctly handling arbitrary nesting depth.  Returns ``None`` if
    ``text[start]`` is not '{' or no matching '}' is found.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


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

    # Strip {"type": "tool_use", ...} JSON objects using balanced brace matching
    # to correctly handle arbitrarily nested structures.
    tool_use_pattern = re.compile(r'\{\s*"type"\s*:\s*"tool_use"')
    while True:
        m = tool_use_pattern.search(cleaned)
        if not m:
            break
        obj = _extract_balanced_braces(cleaned, m.start())
        if obj is None:
            break
        cleaned = cleaned[: m.start()] + cleaned[m.start() + len(obj) :]

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
    # Use balanced brace extraction so nested objects are captured correctly.
    _s4_candidates: list[str] = []
    _s4_offset = 0
    while _s4_offset < len(cleaned):
        _s4_pos = cleaned.find("{", _s4_offset)
        if _s4_pos == -1:
            break
        _s4_obj = _extract_balanced_braces(cleaned, _s4_pos)
        if _s4_obj is None:
            _s4_offset = _s4_pos + 1
            continue
        _s4_candidates.append(_s4_obj)
        _s4_offset = _s4_pos + len(_s4_obj)
    for json_text in _s4_candidates:
        try:
            parsed = json.loads(json_text)
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
