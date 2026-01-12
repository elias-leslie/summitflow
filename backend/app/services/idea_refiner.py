"""Idea refinement service using AI.

Refines raw user ideas into structured, actionable improvement suggestions.
Uses Gemini for cost efficiency per decision d2.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from ..constants import GEMINI_FLASH
from ..storage.connection import get_connection
from .agent_hub_client import AgentHubLLMClient

logger = logging.getLogger(__name__)

REFINEMENT_SYSTEM_PROMPT = """You are an AI that refines game improvement ideas for Monkey Fight, a Phaser.js fighting game.

Your job is to:
1. Reformat the idea for clarity
2. Check if it's feasible to implement
3. Categorize it (bug, feature, content, enhancement)
4. Estimate complexity (simple, medium, complex)
5. Score feasibility (0-1 scale)
6. Reject if inappropriate

REJECTION CRITERIA (respond with rejection_reason if any apply):
- Harmful/offensive content
- Complete rewrite/refactor requests (e.g., "rewrite the whole game", "change the engine")
- Clearly infeasible (requires external services, multiplayer backend, etc.)
- Not game-related
- Too vague to be actionable

Respond ONLY with valid JSON in this exact format:
{
  "refined_text": "Clear, actionable description of the improvement",
  "category": "bug|feature|content|enhancement",
  "complexity": "simple|medium|complex",
  "feasibility_score": 0.0-1.0,
  "rejection_reason": null or "reason for rejection"
}

If the idea should be rejected, still fill in the other fields with your analysis, but include rejection_reason.
"""


@dataclass
class RefinementResult:
    """Result of AI refinement."""

    refined_text: str
    category: str
    complexity: str
    feasibility_score: float
    rejection_reason: str | None = None
    raw_response: str | None = None


def refine_idea(
    raw_text: str,
    additional_context: str | None = None,
    project_id: str = "summitflow",
) -> RefinementResult:
    """Refine a raw idea using AI.

    Args:
        raw_text: The user's original idea text
        additional_context: Optional additional context from retry
        project_id: Project ID for session tracking (default: summitflow)

    Returns:
        RefinementResult with structured data
    """
    prompt = f"User idea: {raw_text}"
    if additional_context:
        prompt += f"\n\nAdditional context: {additional_context}"

    client = AgentHubLLMClient(model=GEMINI_FLASH, provider="gemini", project_id=project_id)
    try:
        response = client.generate(
            prompt=prompt,
            system=REFINEMENT_SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.3,
            purpose="idea_refinement",
        )

        # Parse JSON from response
        content = response.content.strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            content = re.sub(r"```(?:json)?\n?", "", content)
            content = content.strip()

        data = json.loads(content)

        return RefinementResult(
            refined_text=data.get("refined_text", raw_text),
            category=data.get("category", "feature"),
            complexity=data.get("complexity", "medium"),
            feasibility_score=float(data.get("feasibility_score", 0.5)),
            rejection_reason=data.get("rejection_reason"),
            raw_response=response.content,
        )
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response: {e}")
        return RefinementResult(
            refined_text=raw_text,
            category="feature",
            complexity="medium",
            feasibility_score=0.5,
            rejection_reason=None,
            raw_response=response.content if "response" in dir() else None,
        )
    except Exception as e:
        logger.error(f"AI refinement failed: {e}")
        raise
    finally:
        client.close()


SCORING_SYSTEM_PROMPT = """Rate this idea on ease (1-10) and impact (1-10).
Ease: 10=trivial, 5=medium, 1=very hard.
Impact: 10=major improvement, 5=nice, 1=minor.
Reply with ONLY: ease=N impact=N"""


@dataclass
class ScoringResult:
    """Result of AI scoring."""

    ease_score: float
    impact_score: float
    priority_score: float  # ROI = impact / ease


def score_idea(
    refined_text: str,
    category: str,
    complexity: str,
    project_id: str = "summitflow",
) -> ScoringResult:
    """Score an idea for prioritization.

    Args:
        refined_text: The refined idea text
        category: bug/feature/content/enhancement
        complexity: simple/medium/complex
        project_id: Project ID for session tracking (default: summitflow)

    Returns:
        ScoringResult with ease, impact, and priority scores
    """
    prompt = f"""Idea: {refined_text}
Category: {category}
Complexity: {complexity}"""

    client = AgentHubLLMClient(model=GEMINI_FLASH, provider="gemini", project_id=project_id)
    try:
        response = client.generate(
            prompt=prompt,
            system=SCORING_SYSTEM_PROMPT,
            max_tokens=256,
            temperature=0.2,
            purpose="idea_scoring",
        )

        content = response.content.strip()
        logger.info(f"Scoring raw response: {content[:200]}")

        # Handle markdown code blocks
        if "```" in content:
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = content.strip()

        # Try to extract ease and impact scores (handles multiple formats)
        # Format 1: ease=N impact=N
        # Format 2: "ease_score": N, "impact_score": N
        ease_match = re.search(
            r"ease[_\s]*(?:score)?[=:\s]+(\d+(?:\.\d+)?)", content, re.IGNORECASE
        )
        impact_match = re.search(
            r"impact[_\s]*(?:score)?[=:\s]+(\d+(?:\.\d+)?)", content, re.IGNORECASE
        )

        logger.info(f"ease_match: {ease_match}, impact_match: {impact_match}")

        if ease_match and impact_match:
            ease = float(ease_match.group(1))
            impact = float(impact_match.group(1))
            logger.info(f"Extracted scores: ease={ease}, impact={impact}")
        else:
            # Try to find any number patterns
            numbers = re.findall(r"\d+(?:\.\d+)?", content)
            logger.info(f"Found numbers: {numbers}")
            if len(numbers) >= 2:
                ease = float(numbers[0])
                impact = float(numbers[1])
                logger.info(f"Using first two numbers as scores: ease={ease}, impact={impact}")
            else:
                raise ValueError(f"Could not parse scores from: {content[:200]}")

        # ROI = impact / ease (higher is better)
        priority = impact / ease if ease > 0 else 0

        return ScoringResult(
            ease_score=ease,
            impact_score=impact,
            priority_score=round(priority, 2),
        )
    except Exception as e:
        logger.error(f"AI scoring failed: {e}")
        # Default to neutral scores
        return ScoringResult(ease_score=5.0, impact_score=5.0, priority_score=1.0)
    finally:
        client.close()


def update_idea_with_refinement(
    idea_id: str,
    result: RefinementResult,
    project_id: str = "summitflow",
) -> None:
    """Update idea record with refinement results.

    Args:
        idea_id: The idea ID to update
        result: RefinementResult from AI
        project_id: Project ID for session tracking (default: summitflow)
    """
    now = datetime.now(UTC)
    status = "rejected" if result.rejection_reason else "refined"

    # Score the idea if not rejected
    scores = None
    if not result.rejection_reason:
        scores = score_idea(
            result.refined_text, result.category, result.complexity, project_id=project_id
        )

    with get_connection() as conn, conn.cursor() as cur:
        if scores:
            cur.execute(
                """
                UPDATE ideas SET
                    refined_text = %s,
                    category = %s,
                    complexity = %s,
                    feasibility_score = %s,
                    rejection_reason = %s,
                    status = %s,
                    ease_score = %s,
                    impact_score = %s,
                    priority_score = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    result.refined_text,
                    result.category,
                    result.complexity,
                    result.feasibility_score,
                    result.rejection_reason,
                    status,
                    scores.ease_score,
                    scores.impact_score,
                    scores.priority_score,
                    now,
                    idea_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE ideas SET
                    refined_text = %s,
                    category = %s,
                    complexity = %s,
                    feasibility_score = %s,
                    rejection_reason = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    result.refined_text,
                    result.category,
                    result.complexity,
                    result.feasibility_score,
                    result.rejection_reason,
                    status,
                    now,
                    idea_id,
                ),
            )
        conn.commit()
