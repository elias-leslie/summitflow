"""Prompt loading and response parsing for enrichment service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ..context_gatherer import format_context_for_prompt

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt from the prompts directory."""
    path = PROMPTS_DIR / f"{name}.md"
    if path.exists():
        return path.read_text()
    logger.warning("Prompt file not found: %s", path)
    return ""


def parse_enrichment_response(response_text: str) -> dict[str, Any]:
    """Parse JSON from LLM response text.

    Handles markdown code blocks and extracts JSON.
    """
    text = response_text.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    result: dict[str, Any] = json.loads(text)
    return result


def build_enrichment_prompt(raw_request: str, context: dict[str, Any]) -> str:
    """Build the full prompt for task enrichment."""
    system_prompt = load_prompt("task_enrichment")
    formatted_context = format_context_for_prompt(context)

    return f"""{system_prompt}

## Project Context

{formatted_context}

## User's Request

{raw_request}

## Instructions

Based on the user's request and project context, generate a structured task.
Return ONLY valid JSON matching the schema in the prompt above.
Do not include any explanation or markdown outside the JSON."""


__all__ = ["build_enrichment_prompt", "load_prompt", "parse_enrichment_response"]
