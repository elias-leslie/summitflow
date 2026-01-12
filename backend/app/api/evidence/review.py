"""Evidence review endpoints.

User and AI review submission for evidence quality assessment.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...logging_config import get_logger
from ...services.agent_hub_client import AgentType, get_agent
from ...services.evidence_manager import (
    get_evidence_by_id,
    read_evidence_file,
    update_ai_review,
    update_user_review,
)

logger = get_logger(__name__)

router = APIRouter()


class ReviewRequest(BaseModel):
    """Request to submit user review."""

    approved: bool | None = None
    notes: str | None = None


class AgentReviewRequest(BaseModel):
    """Request for agent to review evidence."""

    agent: str = Field(default="gemini", description="Agent type: 'claude' or 'gemini'")
    mode: str = Field(
        default="quality",
        description="Review mode: 'quality' (default) or 'design_audit'",
    )
    focus: str | None = Field(
        None,
        description="Optional focus area for analysis (e.g., 'accessibility', 'performance')",
    )


@router.post("/projects/{project_id}/evidence/{evidence_id}/review")
async def submit_review(
    project_id: str,
    evidence_id: str,
    request: ReviewRequest,
) -> dict[str, Any]:
    """Submit a user review for evidence."""
    success = update_user_review(
        project_id=project_id,
        evidence_id=evidence_id,
        approved=request.approved,
        notes=request.notes,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Evidence not found")

    return {"success": True, "message": "Review submitted"}


def _get_agent_with_fallback(preferred: str, mode: str) -> tuple[Any, str]:
    """Get agent with fallback logic.

    For design_audit mode: Gemini primary, Claude fallback.
    For quality mode: Use requested agent, no fallback.

    Returns:
        Tuple of (agent instance, agent name used)

    Raises:
        HTTPException if no agent available
    """
    if preferred not in ("claude", "gemini"):
        raise HTTPException(status_code=400, detail="Agent must be 'claude' or 'gemini'")

    if mode == "design_audit":
        # Design audit: Gemini primary, Claude fallback
        try:
            agent = get_agent("gemini")
            if agent.is_available():
                return agent, "gemini"
        except RuntimeError:
            pass

        try:
            agent = get_agent("claude")
            if agent.is_available():
                logger.warning("design_audit_fallback", reason="Gemini unavailable, using Claude")
                return agent, "claude"
        except RuntimeError:
            pass

        raise HTTPException(
            status_code=503,
            detail="No agents available for design audit. Both Gemini and Claude unavailable.",
        )
    else:
        # Quality mode: Use requested agent only
        agent_type: AgentType = "claude" if preferred == "claude" else "gemini"
        try:
            agent = get_agent(agent_type)
            if not agent.is_available():
                raise HTTPException(
                    status_code=503,
                    detail=f"{preferred} agent is not available. Check CLI installation.",
                )
            return agent, preferred
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None


def _build_quality_prompt(
    metadata: dict[str, Any],
    console_summary: dict[str, Any],
    network_summary: dict[str, Any],
    page_state: dict[str, Any],
    performance: dict[str, Any],
    focus: str | None,
) -> tuple[str, str]:
    """Build prompt for quality review mode."""
    prompt = f"""Analyze this UI evidence capture and identify issues.

## Page Information
- URL: {metadata.get("url", "Unknown")}
- Title: {metadata.get("pageTitle", "Unknown")}
- Captured: {metadata.get("capturedAt", "Unknown")}
- Viewport: {metadata.get("viewport", {})}

## Console Analysis
- Errors: {console_summary.get("errorCount", 0)}
- Warnings: {console_summary.get("warningCount", 0)}

Error Details:
{json.dumps(console_summary.get("errors", [])[:5], indent=2)}

Warning Details:
{json.dumps(console_summary.get("warnings", [])[:3], indent=2)}

## Network Analysis
- Total Requests: {network_summary.get("totalRequests", 0)}
- Failed Requests: {network_summary.get("failedRequests", 0)}

Failed Request Details:
{json.dumps(network_summary.get("failures", [])[:5], indent=2)}

Slow Requests (>3s):
{json.dumps(network_summary.get("slowRequests", [])[:3], indent=2)}

## Page State
- Has Content: {page_state.get("hasContent", False)}
- Key Elements: {json.dumps(page_state.get("keyElements", {}), indent=2)}
- Visible Text Sample: {page_state.get("visibleTextSample", "")[:200]}

## Performance
- Page Load: {performance.get("pageLoadMs", "N/A")} ms
- DOM Ready: {performance.get("domContentLoadedMs", "N/A")} ms
- LCP: {performance.get("largestContentfulPaintMs", "N/A")} ms

{f"Focus Area: {focus}" if focus else ""}

Based on this evidence, provide:

1. **ISSUES** - List each problem found with severity (critical/high/medium/low)
2. **PROPOSED FEATURES** - Suggested features to fix each issue
3. **OVERALL ASSESSMENT** - Quality score (0-100) and summary

Format your response as JSON:
```json
{{
  "issues": [
    {{
      "id": "issue-1",
      "severity": "high",
      "category": "error|performance|ux|accessibility",
      "title": "Brief title",
      "description": "Detailed description",
      "evidence": "What in the capture shows this issue",
      "proposed_fix": {{
        "feature_name": "Suggested feature name",
        "description": "What the feature should do",
        "acceptance_criteria": ["AC 1", "AC 2"]
      }}
    }}
  ],
  "overall": {{
    "score": 75,
    "status": "needs_work|acceptable|good",
    "summary": "Brief overall assessment"
  }}
}}
```
"""
    system = """You are a UI quality analyst. Analyze evidence captures and identify issues.
Be specific and actionable. Cite evidence from the capture data.
Always format response as valid JSON."""

    return prompt, system


def _build_design_audit_prompt(
    metadata: dict[str, Any],
    page_state: dict[str, Any],
    design_rules: list[dict[str, Any]],
    sub_elements: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Build prompt for design audit mode."""
    # Format rules by category for the prompt
    rules_by_category: dict[str, list[dict[str, Any]]] = {}
    for rule in design_rules:
        cat = rule.get("category", "other")
        if cat not in rules_by_category:
            rules_by_category[cat] = []
        rules_by_category[cat].append(rule)

    rules_text = ""
    for category, rules in rules_by_category.items():
        rules_text += f"\n### {category.title()}\n"
        for rule in rules:
            rules_text += f"- **{rule['rule_id']}**: {rule['name']}\n"
            req = rule.get("requirements", {})
            if req:
                rules_text += f"  Requirements: {json.dumps(req)}\n"

    # Format sub-elements if present
    sub_elements_text = ""
    if sub_elements:
        sub_elements_text = "\n## Interactive Sub-Elements (require individual verification)\n"
        for el in sub_elements:
            el_type = el.get("element_type", "unknown")
            label = el.get("label", "unlabeled")
            captured = "Yes" if el.get("last_captured_at") else "No"
            sub_elements_text += f"- **{el_type}**: {label} (captured: {captured})\n"
        sub_elements_text += "\nNote: Sub-elements like tabs and accordions may need individual screenshots for full coverage.\n"

    prompt = f"""Perform a design audit of this UI against the provided design standards.

## Page Information
- URL: {metadata.get("url", "Unknown")}
- Title: {metadata.get("pageTitle", "Unknown")}
- Viewport: {metadata.get("viewport", {})}

## Page State
- Has Content: {page_state.get("hasContent", False)}
- Key Elements: {json.dumps(page_state.get("keyElements", {}), indent=2)}
- Visible Text Sample: {page_state.get("visibleTextSample", "")[:300]}
{sub_elements_text}
## Design Standards to Check Against
{rules_text}

Analyze the UI evidence (screenshot and page data) and evaluate compliance with each design rule.

Provide a detailed compliance report in JSON format:
```json
{{
  "compliance_report": {{
    "passed_rules": [
      {{
        "rule_id": "layout-001",
        "rule_name": "Content Width",
        "evidence": "What shows compliance"
      }}
    ],
    "violated_rules": [
      {{
        "rule_id": "typography-001",
        "rule_name": "Font Family",
        "severity": "high|medium|low",
        "violation": "What is wrong",
        "expected": "What the standard requires",
        "actual": "What was observed",
        "recommendation": "How to fix"
      }}
    ],
    "sub_element_coverage": {{
      "total": 0,
      "captured": 0,
      "uncaptured": ["list of uncaptured element labels"]
    }},
    "overall_score": 75,
    "summary": "Brief compliance summary",
    "recommendations": [
      "Priority recommendation 1",
      "Priority recommendation 2"
    ]
  }}
}}
```

Score calculation:
- 100 = All rules pass
- Deduct points per violation: high severity (-15), medium (-10), low (-5)
- Deduct 2 points per uncaptured sub-element (coverage gap)
- Minimum score is 0
"""

    system = """You are a UI/UX design auditor. Evaluate screenshots and page data against design standards.
Be objective and specific. Cite visual evidence for each assessment.
Include sub-element coverage analysis when sub-elements are present.
Always format response as valid JSON with compliance_report structure."""

    return prompt, system


def _parse_agent_response(response_text: str, mode: str) -> dict[str, Any]:
    """Parse agent response based on mode."""
    json_match = None

    if mode == "design_audit":
        patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*(\{.*?\})\s*```",
            r"(\{[\s\S]*\"compliance_report\"[\s\S]*\})",
        ]
    else:
        patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*(\{.*?\})\s*```",
            r"(\{[\s\S]*\"issues\"[\s\S]*\})",
        ]

    for pattern in patterns:
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
            json_match = match.group(1)
            break

    if json_match:
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(json_match)
            if isinstance(parsed, dict):
                return parsed

    # Fallback structure based on mode
    if mode == "design_audit":
        return {
            "compliance_report": {
                "passed_rules": [],
                "violated_rules": [],
                "overall_score": 50,
                "summary": "Could not parse structured response. Raw analysis available.",
                "recommendations": [],
            },
            "raw_analysis": response_text,
        }
    else:
        return {
            "issues": [],
            "overall": {
                "score": 50,
                "status": "needs_work",
                "summary": "Could not parse structured response. Raw analysis available.",
            },
            "raw_analysis": response_text,
        }


@router.post("/projects/{project_id}/evidence/{evidence_id}/agent-review")
async def agent_review(
    project_id: str,
    evidence_id: str,
    request: AgentReviewRequest,
) -> dict[str, Any]:
    """Request an AI agent to analyze evidence.

    Modes:
    - quality (default): Analyze for bugs, performance, UX issues
    - design_audit: Compare against project design standards, generate compliance report
    """
    # Validate mode
    if request.mode not in ("quality", "design_audit"):
        raise HTTPException(status_code=400, detail="Mode must be 'quality' or 'design_audit'")

    evidence = get_evidence_by_id(project_id, evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_data = read_evidence_file(project_id, evidence_id, evidence.get("version"))
    if not evidence_data:
        raise HTTPException(status_code=404, detail="Evidence data not found")

    # Get agent with fallback for design_audit mode
    agent, agent_used = _get_agent_with_fallback(request.agent, request.mode)

    console_summary = evidence_data.get("console", {})
    network_summary = evidence_data.get("network", {})
    page_state = evidence_data.get("pageState", {})
    performance = evidence_data.get("performance", {})
    metadata = evidence_data.get("metadata", {})

    # Build prompt based on mode
    if request.mode == "design_audit":
        # Import here to avoid circular import
        from ...storage.design_standards import get_effective_rules
        from ...storage.explorer_sub_elements import get_elements_for_entry

        design_rules = get_effective_rules(project_id)
        if not design_rules:
            raise HTTPException(
                status_code=400,
                detail="No design standards found for project. Create standards first.",
            )

        # Get sub-elements if evidence is linked to an explorer entry
        sub_elements: list[dict[str, Any]] = []
        explorer_entry_id = evidence.get("explorer_entry_id")
        if explorer_entry_id:
            # TypedDict is compatible with dict[str, Any] at runtime
            sub_elements = list(get_elements_for_entry(explorer_entry_id))  # type: ignore[arg-type]

        prompt, system = _build_design_audit_prompt(
            metadata, page_state, design_rules, sub_elements or None
        )
    else:
        prompt, system = _build_quality_prompt(
            metadata, console_summary, network_summary, page_state, performance, request.focus
        )

    try:
        response = agent.generate(prompt=prompt, system=system, max_tokens=4096)
        response_text = response.content
        analysis = _parse_agent_response(response_text, request.mode)

        # Extract score and determine status based on mode
        if request.mode == "design_audit":
            compliance = analysis.get("compliance_report", {})
            score = compliance.get("overall_score", 50)
        else:
            overall = analysis.get("overall", {})
            score = overall.get("score", 50)

        if score >= 80:
            quality_status = "passed"
        elif score >= 50:
            quality_status = "needs_review"
        else:
            quality_status = "failed"

        confidence = score / 100.0

        update_ai_review(
            project_id=project_id,
            evidence_id=evidence_id,
            quality_status=quality_status,
            confidence=confidence,
            ai_evidence=json.dumps(analysis),
            reviewed_by=f"{agent_used}:{agent.get_model_name()}",
        )

        log_kwargs: dict[str, Any] = {
            "project_id": project_id,
            "evidence_id": evidence_id,
            "agent": agent_used,
            "mode": request.mode,
            "score": score,
        }
        if request.mode == "design_audit":
            compliance = analysis.get("compliance_report", {})
            log_kwargs["violations"] = len(compliance.get("violated_rules", []))
        else:
            log_kwargs["issues_found"] = len(analysis.get("issues", []))

        logger.info("agent_review_complete", **log_kwargs)

        # Build response based on mode
        response_data: dict[str, Any] = {
            "success": True,
            "agent": agent_used,
            "model": agent.get_model_name(),
            "mode": request.mode,
            "quality_status": quality_status,
            "confidence": confidence,
        }

        if request.mode == "design_audit":
            response_data["compliance_report"] = analysis.get("compliance_report", {})
        else:
            response_data["analysis"] = analysis

        return response_data

    except RuntimeError as e:
        logger.error("agent_review_failed", error=str(e), mode=request.mode)
        raise HTTPException(status_code=500, detail=str(e)) from None
