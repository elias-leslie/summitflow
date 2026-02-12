"""Design analysis endpoints for mockups API."""

from fastapi import APIRouter

from .mockups_models import AnalyzePageRequest, AnalyzePageResponse

router = APIRouter()


@router.post(
    "/projects/{project_id}/mockups/analyze-page",
    response_model=AnalyzePageResponse,
)
async def analyze_page(
    project_id: str,
    request: AnalyzePageRequest,
) -> AnalyzePageResponse:
    """Analyze a page's design and generate improvement recommendations.

    This endpoint:
    1. Captures a screenshot of the specified URL
    2. Analyzes it against the project's design standards
    3. Generates specific improvement recommendations
    4. Stores the result as a mockup record

    The mockup record will contain:
    - The captured screenshot (file_path)
    - The analysis and recommendations (generation_prompt)
    - Metadata about the analysis
    """
    from ..services.mockup_generator import analyze_page_design

    result = await analyze_page_design(
        project_id=project_id,
        page_url=request.page_url,
        page_path=request.page_path,
    )

    return AnalyzePageResponse(
        success=result.success,
        mockup_id=result.mockup_id,
        screenshot_path=result.screenshot_path,
        mockup_image_path=result.mockup_image_path,
        recommendations=result.recommendations,
        issues_found=result.issues_found,
        error=result.error,
        generation_time_ms=result.generation_time_ms,
    )
