"""Tasks API - Prompt cleanup endpoint.

AI-powered cleanup and refinement of raw task prompts.
"""

from __future__ import annotations

import json

from fastapi import APIRouter

from ...logging_config import get_logger
from ...schemas.tasks import CleanupPromptRequest, CleanupPromptResponse

logger = get_logger(__name__)

router = APIRouter()


def _build_cleanup_prompt(raw_request: str) -> str:
    """Build the AI prompt for cleaning up a raw task request."""
    return f"""Clean up and refine this task request. Fix grammar, clarify intent, and expand abbreviations. Keep the meaning unchanged.

Original:
{raw_request}

Return JSON:
{{"cleaned_prompt": "...", "changes_made": ["change1", "change2"]}}"""


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from AI response text."""
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _parse_cleanup_response(raw_text: str) -> dict:
    """Strip markdown fences and parse the JSON response from the AI."""
    text = _strip_markdown_fences(raw_text)
    return json.loads(text)


def _call_cleanup_ai(raw_request: str) -> CleanupPromptResponse | None:
    """Call the AI service to clean up the prompt.

    Returns a CleanupPromptResponse on success, or None if the client is
    unavailable.
    """
    from ...services.agent_hub_client import AgentHubLLMClient

    client = AgentHubLLMClient(agent_slug="analyst")
    if not client.is_available():
        return None

    prompt = _build_cleanup_prompt(raw_request)
    response = client.generate(prompt, temperature=0.2)
    data = _parse_cleanup_response(response.content.strip())

    return CleanupPromptResponse(
        cleaned_prompt=data.get("cleaned_prompt", raw_request),
        changes_made=data.get("changes_made", []),
    )


@router.post(
    "/projects/{project_id}/tasks/cleanup-prompt",
    response_model=CleanupPromptResponse,
)
async def cleanup_prompt_endpoint(
    project_id: str,
    request: CleanupPromptRequest,
) -> CleanupPromptResponse:
    """Clean up and refine a raw prompt using AI.

    Uses Gemini Flash for fast, cheap text cleanup.

    Args:
        project_id: Project ID
        request: Request with raw_request text

    Returns:
        CleanupPromptResponse with cleaned text and changes list
    """
    try:
        result = _call_cleanup_ai(request.raw_request)
        if result is None:
            return CleanupPromptResponse(
                cleaned_prompt=request.raw_request,
                changes_made=["Gemini unavailable - no changes made"],
            )
        return result
    except Exception as e:
        logger.warning("cleanup_prompt_failed", error=str(e))
        return CleanupPromptResponse(
            cleaned_prompt=request.raw_request,
            changes_made=[f"Cleanup failed: {e}"],
        )
