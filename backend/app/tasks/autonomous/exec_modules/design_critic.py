"""Structured screenshot-based design critic for frontend-heavy tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ....services.context_gatherer.design_collector import gather_design_standards_context
from ....services.mockup_generator.analysis.vision import analyze_screenshot_with_prompt
from ._prompt_fetch import get_prompt_template
from ._prompt_json import parse_json_response

_SLUG_FRONTEND_DESIGN_CRITIC = "frontend-design-critic"
_DESIGN_CRITIC_AGENT_SLUG = "designer"


def _format_list(items: list[str]) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def _normalize_scores(scores: Any) -> dict[str, float]:
    if not isinstance(scores, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, value in scores.items():
        try:
            normalized[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return normalized


def run_design_critic(
    project_id: str,
    page_url: str,
    screenshot_path: Path,
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    """Run the design critic and return structured scoring + findings."""
    design_context = gather_design_standards_context(project_id) or "# Design Standards\n\n(None found)"
    prompt = get_prompt_template(_SLUG_FRONTEND_DESIGN_CRITIC).format_map(
        {
            "page_url": page_url,
            "design_standards": design_context,
            "design_criteria": json.dumps(execution_contract.get("design_criteria") or {}, indent=2),
            "risk_notes": _format_list(execution_contract.get("risk_notes") or []),
        }
    )
    response_text, error = analyze_screenshot_with_prompt(
        project_id,
        screenshot_path,
        prompt,
        agent_slug=_DESIGN_CRITIC_AGENT_SLUG,
    )
    if error or response_text is None:
        return {
            "passed": False,
            "summary": error or "Design critic unavailable",
            "scores": {},
            "overall_score": 0.0,
            "findings": [],
        }

    parsed = parse_json_response(response_text)
    scores = _normalize_scores(parsed.get("scores"))
    overall_score = float(parsed.get("overall_score") or 0.0)
    findings = [
        str(item).strip()
        for item in parsed.get("findings", [])
        if str(item).strip()
    ]
    passed = parsed.get("passed")
    if not isinstance(passed, bool):
        passed = overall_score >= 7.0

    return {
        "passed": passed,
        "summary": str(parsed.get("summary") or response_text[:240]).strip(),
        "scores": scores,
        "overall_score": overall_score,
        "findings": findings,
    }
