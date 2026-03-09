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


def _extract_json_candidates(text: str) -> list[str]:
    """Return all balanced JSON objects found in *text*, in order."""
    candidates: list[str] = []
    offset = 0
    while offset < len(text):
        pos = text.find("{", offset)
        if pos == -1:
            break
        obj = _extract_balanced_braces(text, pos)
        if obj is None:
            offset = pos + 1
            continue
        candidates.append(obj)
        offset = pos + len(obj)
    return candidates


def _verdict_from_str(value: str) -> dict[str, Any] | None:
    """Parse *value* as JSON and return it if it contains 'verdict'."""
    try:
        inner = json.loads(value)
        if isinstance(inner, dict) and "verdict" in inner:
            return inner
    except json.JSONDecodeError:
        pass
    return None


def _check_nested_verdict(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Return a verdict dict buried under a common wrapper subkey, or None."""
    for subkey in ("input", "result", "output", "content"):
        sub = parsed.get(subkey)
        if isinstance(sub, dict) and "verdict" in sub:
            return sub
        if isinstance(sub, str):
            result = _verdict_from_str(sub)
            if result is not None:
                return result
    return None


def _try_flat_verdict(cleaned: str) -> dict[str, Any] | None:
    """Strategy 2: flat JSON object with a 'verdict' key."""
    m = re.search(r'\{[^{}]*"verdict"[^{}]*\}', cleaned, re.DOTALL)
    if m:
        try:
            parsed: dict[str, Any] = json.loads(m.group())
            if "verdict" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _try_fenced_code(cleaned: str) -> dict[str, Any] | None:
    """Strategy 3: fenced code block containing JSON."""
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if "verdict" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _try_nested_json(cleaned: str) -> dict[str, Any] | None:
    """Strategy 4: scan all balanced JSON objects and walk subkeys."""
    for json_text in _extract_json_candidates(cleaned):
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError:
            continue
        if "verdict" in parsed:
            return parsed
        result = _check_nested_verdict(parsed)
        if result is not None:
            return result
    return None


def _try_greedy_json(content: str) -> dict[str, Any] | None:
    """Strategy 5: greedy match on the original content (pre-strip fallback)."""
    try:
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            parsed = json.loads(m.group())
            if "verdict" in parsed:
                return parsed
    except json.JSONDecodeError:
        pass
    return None


def _try_keywords(content: str) -> dict[str, Any] | None:
    """Strategy 6: keyword-based text fallback."""
    upper = content.upper()
    for keyword in ("APPROVED", "PLAN_DEFECT", "ESCALATE"):
        if keyword in upper:
            return {"verdict": keyword, "summary": content}
    return None


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
    cleaned = _strip_tool_call_artifacts(content)
    result = (
        _try_flat_verdict(cleaned)
        or _try_fenced_code(cleaned)
        or _try_nested_json(cleaned)
        or _try_greedy_json(content)
        or _try_keywords(content)
    )
    return result if result is not None else {"verdict": "NEEDS_FIX", "summary": content}
