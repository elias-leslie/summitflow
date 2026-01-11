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


@router.post("/projects/{project_id}/evidence/{evidence_id}/agent-review")
async def agent_review(
    project_id: str,
    evidence_id: str,
    request: AgentReviewRequest,
) -> dict[str, Any]:
    """Request an AI agent to analyze evidence and propose issues/features.

    The agent analyzes screenshot content, console errors, network failures,
    page state, and performance metrics. Returns proposed issues with fixes.
    """
    evidence = get_evidence_by_id(project_id, evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence_data = read_evidence_file(project_id, evidence_id, evidence.get("version"))
    if not evidence_data:
        raise HTTPException(status_code=404, detail="Evidence data not found")

    try:
        if request.agent not in ("claude", "gemini"):
            raise HTTPException(status_code=400, detail="Agent must be 'claude' or 'gemini'")
        agent_type: AgentType = "claude" if request.agent == "claude" else "gemini"
        agent = get_agent(agent_type)
        if not agent.is_available():
            raise HTTPException(
                status_code=503,
                detail=f"{request.agent} agent is not available. Check CLI installation.",
            )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    console_summary = evidence_data.get("console", {})
    network_summary = evidence_data.get("network", {})
    page_state = evidence_data.get("pageState", {})
    performance = evidence_data.get("performance", {})
    metadata = evidence_data.get("metadata", {})

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

{f"Focus Area: {request.focus}" if request.focus else ""}

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

    try:
        response = agent.generate(prompt=prompt, system=system, max_tokens=4096)

        response_text = response.content
        analysis = None

        json_match = None
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
                analysis = json.loads(json_match)

        if not analysis:
            analysis = {
                "issues": [],
                "overall": {
                    "score": 50,
                    "status": "needs_work",
                    "summary": "Could not parse structured response. Raw analysis available.",
                },
                "raw_analysis": response_text,
            }

        overall = analysis.get("overall", {})
        score = overall.get("score", 50)

        if score >= 80:
            quality_status = "passed"
            confidence = score / 100.0
        elif score >= 50:
            quality_status = "needs_review"
            confidence = score / 100.0
        else:
            quality_status = "failed"
            confidence = score / 100.0

        update_ai_review(
            project_id=project_id,
            evidence_id=evidence_id,
            quality_status=quality_status,
            confidence=confidence,
            ai_evidence=json.dumps(analysis),
            reviewed_by=f"{request.agent}:{agent.get_model_name()}",
        )

        logger.info(
            "agent_review_complete",
            project_id=project_id,
            evidence_id=evidence_id,
            agent=request.agent,
            issues_found=len(analysis.get("issues", [])),
            score=score,
        )

        return {
            "success": True,
            "agent": request.agent,
            "model": agent.get_model_name(),
            "analysis": analysis,
            "quality_status": quality_status,
            "confidence": confidence,
        }

    except RuntimeError as e:
        logger.error("agent_review_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None
