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
        from ...services.agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(agent_slug="analyst")
        if not client.is_available():
            return CleanupPromptResponse(
                cleaned_prompt=request.raw_request,
                changes_made=["Gemini unavailable - no changes made"],
            )

        prompt = f"""Clean up and refine this task request. Fix grammar, clarify intent, and expand abbreviations. Keep the meaning unchanged.

Original:
{request.raw_request}

Return JSON:
{{"cleaned_prompt": "...", "changes_made": ["change1", "change2"]}}"""

        response = client.generate(prompt, temperature=0.2)

        text = response.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        data = json.loads(text.strip())

        return CleanupPromptResponse(
            cleaned_prompt=data.get("cleaned_prompt", request.raw_request),
            changes_made=data.get("changes_made", []),
        )

    except Exception as e:
        logger.warning("cleanup_prompt_failed", error=str(e))
        return CleanupPromptResponse(
            cleaned_prompt=request.raw_request,
            changes_made=[f"Cleanup failed: {e}"],
        )
