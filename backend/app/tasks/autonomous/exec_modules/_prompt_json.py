"""JSON extraction helpers for prompt-backed evaluator responses."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_response(content: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response."""
    try:
        decoder = json.JSONDecoder()
        match = re.search(r"\{", content)
        if match:
            parsed, _ = decoder.raw_decode(content[match.start() :])
            if isinstance(parsed, dict):
                return parsed
    except json.JSONDecodeError:
        pass
    return {}
