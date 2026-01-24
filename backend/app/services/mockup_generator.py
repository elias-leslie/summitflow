"""Mockup generator service for design audit workflows.

Uses Agent Hub for image generation (Gemini) with Claude HTML as fallback.
Mockups are stored in the mockups table.
"""

from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_hub.exceptions import AgentHubError

from ..constants import CLAUDE_SONNET, GEMINI_IMAGE, GEMINI_PRO
from ..logging_config import get_logger
from ..storage import mockups as mockups_storage
from .agent_hub_client import get_sync_client

logger = get_logger(__name__)

# Directory for storing mockup images
MOCKUP_BASE_DIR = Path("/tmp/summitflow/mockups")

# Note: Agent Hub configuration moved to agent_hub_client.py


def _generate_mockup_id() -> str:
    """Generate a new mockup ID in the format mk-{uuid}."""
    return f"mk-{uuid.uuid4().hex[:12]}"


@dataclass
class MockupResult:
    """Result of mockup generation."""

    success: bool
    mockup_id: str | None = None
    db_id: int | None = None
    image_path: str | None = None
    error: str | None = None
    generator: str | None = None
    generation_time_ms: int = 0


def _get_agent_hub_client() -> Any:
    """Get Agent Hub client for image generation."""
    return get_sync_client()


def _build_mockup_prompt(
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> str:
    """Build the prompt for mockup generation.

    Args:
        page_info: Page metadata from explorer (path, title, etc.)
        design_standard: Design standard with rules
        design_direction: Optional specific design direction

    Returns:
        Formatted prompt for image generation
    """
    page_path = page_info.get("path", "/")
    page_title = page_info.get("name", "Page")
    page_description = page_info.get("description", "")

    # Extract key rules from design standard
    rules = design_standard.get("rules", [])
    color_rules = [r for r in rules if r.get("category") == "colors"]
    typography_rules = [r for r in rules if r.get("category") == "typography"]
    layout_rules = [r for r in rules if r.get("category") == "layout"]
    component_rules = [r for r in rules if r.get("category") == "components"]

    def format_rules(rule_list: list[dict[str, Any]], max_rules: int = 3) -> str:
        if not rule_list:
            return "None specified"
        return "\n".join(
            f"- {r.get('name', 'Rule')}: {r.get('value', '')}" for r in rule_list[:max_rules]
        )

    prompt = f"""Generate a high-fidelity UI mockup for a web application page.

PAGE CONTEXT:
- Path: {page_path}
- Title: {page_title}
- Description: {page_description}

DESIGN STANDARD: {design_standard.get("name", "Default")}

COLOR PALETTE:
{format_rules(color_rules)}

TYPOGRAPHY:
{format_rules(typography_rules)}

LAYOUT RULES:
{format_rules(layout_rules)}

COMPONENT PATTERNS:
{format_rules(component_rules)}

REQUIREMENTS:
1. Create a complete, professional UI mockup at 1920x1080 resolution
2. Use a dark theme with the specified color palette
3. Include realistic content (not lorem ipsum)
4. Show proper spacing, alignment, and visual hierarchy
5. Include navigation, content area, and any relevant UI elements
6. Text should be legible and rendered clearly

{f"DESIGN DIRECTION: {design_direction}" if design_direction else ""}

Output a single image that represents the target design state for this page."""

    return prompt


def generate_mockup_gemini(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> MockupResult:
    """Generate mockup using Agent Hub image generation (Gemini backend).

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        page_info: Page metadata from explorer
        design_standard: Design standard with rules
        design_direction: Optional specific design direction

    Returns:
        MockupResult with mockup details
    """
    start_time = time.monotonic()

    try:
        client = _get_agent_hub_client()
        prompt = _build_mockup_prompt(page_info, design_standard, design_direction)

        # Generate image using Agent Hub
        response = client.generate_image(
            prompt=prompt,
            project_id="summitflow",
            purpose="mockup_generation",
            model=GEMINI_IMAGE,
            size="1920x1080",
        )

        # Decode base64 image data
        image_bytes = base64.b64decode(response.image_base64)

        # Determine file extension from mime type
        ext = "png"
        if response.mime_type == "image/jpeg":
            ext = "jpg"
        elif response.mime_type == "image/webp":
            ext = "webp"

        # Save image to file
        mockup_id = _generate_mockup_id()
        mockup_dir = MOCKUP_BASE_DIR / project_id / mockup_id
        mockup_dir.mkdir(parents=True, exist_ok=True)

        image_path = mockup_dir / f"mockup.{ext}"
        image_path.write_bytes(image_bytes)

        generation_time = int((time.monotonic() - start_time) * 1000)

        # Store in mockups table
        page_path = page_info.get("path", "/")
        page_name = page_info.get("name", "Generated mockup")

        mockup = mockups_storage.create_mockup(
            project_id=project_id,
            name=f"Mockup: {page_name}",
            description=f"Generated mockup for {page_path}",
            mockup_type="page",
            file_path=str(image_path),
            page_path=page_path,
            generator="gemini",
            generation_prompt=prompt,
            generation_time_ms=generation_time,
        )

        logger.info(
            "mockup_generated",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            mockup_id=mockup["mockup_id"],
            generator="gemini",
            generation_time_ms=generation_time,
            session_id=response.session_id,
        )

        return MockupResult(
            success=True,
            mockup_id=mockup["mockup_id"],
            db_id=mockup["id"],
            image_path=str(image_path),
            generator="gemini",
            generation_time_ms=generation_time,
        )

    except AgentHubError as e:
        logger.error(
            "mockup_generation_failed",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            generator="gemini",
            error=str(e),
        )
        return MockupResult(
            success=False,
            error=str(e),
            generator="gemini",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )
    except Exception as e:
        logger.error(
            "mockup_generation_failed",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            generator="gemini",
            error=str(e),
        )
        return MockupResult(
            success=False,
            error=str(e),
            generator="gemini",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )


def generate_mockup_claude_fallback(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> MockupResult:
    """Generate HTML mockup using Claude as fallback.

    Generates an HTML/CSS prototype instead of an image.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        page_info: Page metadata from explorer
        design_standard: Design standard with rules
        design_direction: Optional specific design direction

    Returns:
        MockupResult with mockup details
    """
    from .agent_hub_client import get_agent

    start_time = time.monotonic()

    try:
        claude = get_agent("claude", model=CLAUDE_SONNET)
        prompt = _build_mockup_prompt(page_info, design_standard, design_direction)

        # Modify prompt for HTML output
        html_prompt = f"""{prompt}

Since I cannot generate images, create a complete HTML/CSS mockup that:
1. Uses inline styles or a <style> block
2. Implements the color palette and typography specified
3. Creates a realistic, interactive prototype
4. Is self-contained in a single HTML file

Output ONLY the HTML code, no explanation."""

        response = claude.generate(
            prompt=html_prompt,
            system="You are a UI designer creating HTML/CSS prototypes. Output only valid HTML.",
            temperature=0.7,
            purpose="mockup_generation",
        )

        html_content = response.content.strip()

        # Extract HTML if wrapped in code blocks
        if "```html" in html_content:
            html_content = html_content.split("```html")[1].split("```")[0].strip()
        elif "```" in html_content:
            html_content = html_content.split("```")[1].split("```")[0].strip()

        # Save HTML to file
        mockup_id = _generate_mockup_id()
        mockup_dir = MOCKUP_BASE_DIR / project_id / mockup_id
        mockup_dir.mkdir(parents=True, exist_ok=True)

        html_path = mockup_dir / "mockup.html"
        html_path.write_text(html_content)

        generation_time = int((time.monotonic() - start_time) * 1000)

        # Store in mockups table
        page_path = page_info.get("path", "/")
        page_name = page_info.get("name", "Generated mockup")

        mockup = mockups_storage.create_mockup(
            project_id=project_id,
            name=f"Mockup: {page_name}",
            description=f"Generated HTML mockup for {page_path}",
            mockup_type="page",
            file_path=str(html_path),
            content=html_content,
            page_path=page_path,
            generator="claude",
            generation_prompt=html_prompt,
            generation_time_ms=generation_time,
        )

        logger.info(
            "mockup_generated",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            mockup_id=mockup["mockup_id"],
            generator="claude",
            generation_time_ms=generation_time,
        )

        return MockupResult(
            success=True,
            mockup_id=mockup["mockup_id"],
            db_id=mockup["id"],
            image_path=str(html_path),
            generator="claude",
            generation_time_ms=generation_time,
        )

    except Exception as e:
        logger.error(
            "mockup_generation_failed",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            generator="claude",
            error=str(e),
        )
        return MockupResult(
            success=False,
            error=str(e),
            generator="claude",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )


def generate_mockup(
    project_id: str,
    explorer_entry_id: int,
    standards_id: str = "base",
    design_direction: str | None = None,
    page_info: dict[str, Any] | None = None,
) -> MockupResult:
    """Generate a mockup for a page using design standards.

    Uses Agent Hub (Gemini) as primary, Claude HTML as fallback.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        standards_id: Design standard ID to use (default: "base")
        design_direction: Optional specific design direction
        page_info: Page info (if not provided, fetched from explorer)

    Returns:
        MockupResult with evidence details
    """
    # Get page info if not provided
    if page_info is None:
        from ..storage.explorer_entries import get_entry_by_id

        entry = get_entry_by_id(explorer_entry_id)
        if not entry:
            return MockupResult(
                success=False,
                error=f"Explorer entry {explorer_entry_id} not found",
            )
        page_info = {
            "path": entry.get("path"),
            "name": entry.get("name"),
            "description": entry.get("description"),
        }

    # Get design standard
    from ..storage.design_standards import get_base_standard, get_project_standard

    design_standard = None
    if standards_id == "base":
        design_standard = get_base_standard()
    else:
        design_standard = get_project_standard(project_id, standards_id)

    if not design_standard:
        design_standard = get_base_standard()

    if not design_standard:
        return MockupResult(
            success=False,
            error=f"Design standard '{standards_id}' not found",
        )

    # Try Agent Hub (Gemini) first, fallback to Claude
    result = generate_mockup_gemini(
        project_id=project_id,
        explorer_entry_id=explorer_entry_id,
        page_info=page_info,
        design_standard=design_standard,
        design_direction=design_direction,
    )

    if not result.success:
        logger.info(
            "falling_back_to_claude",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            gemini_error=result.error,
        )
        result = generate_mockup_claude_fallback(
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            page_info=page_info,
            design_standard=design_standard,
            design_direction=design_direction,
        )

    return result


# ============================================================================
# Page Design Analysis - Analyze existing page against design standards
# ============================================================================


@dataclass
class DesignAnalysisResult:
    """Result of page design analysis."""

    success: bool
    mockup_id: str | None = None
    screenshot_path: str | None = None
    mockup_image_path: str | None = None
    recommendations: str | None = None
    issues_found: int = 0
    error: str | None = None
    generation_time_ms: int = 0


async def _capture_page_screenshot(
    url: str,
    output_path: Path,
    *,
    width: int = 1280,
    height: int = 720,
    full_page: bool = True,
) -> tuple[bool, str | None]:
    """Capture a screenshot of a URL using agent-browser.

    Args:
        url: URL to capture
        output_path: Path to save screenshot
        width: Viewport width
        height: Viewport height
        full_page: Whether to capture full page

    Returns:
        Tuple of (success, error_message)
    """
    import asyncio
    import shlex

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Build command chain for agent-browser
        # 1. Open URL
        # 2. Set viewport
        # 3. Wait for network idle
        # 4. Take screenshot
        # 5. Close browser
        full_flag = "--full" if full_page else ""
        cmd = (
            f"agent-browser open {shlex.quote(url)} && "
            f"agent-browser set viewport {width} {height} && "
            f"agent-browser wait --load networkidle && "
            f"agent-browser screenshot {shlex.quote(str(output_path))} {full_flag} && "
            f"agent-browser close"
        )

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() or stdout.decode().strip()
            return False, f"Screenshot failed: {error_msg[:200]}"

        if not output_path.exists():
            return False, "Screenshot file not created"

        return True, None

    except TimeoutError:
        # Try to close browser if still open
        try:
            close_proc = await asyncio.create_subprocess_shell(
                "agent-browser close",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(close_proc.communicate(), timeout=5)
        except Exception:
            pass
        return False, "Screenshot operation timed out"
    except Exception as e:
        logger.error("screenshot_capture_failed", url=url, error=str(e))
        return False, str(e)


def _build_design_analysis_prompt(
    design_rules: list[dict[str, Any]],
    page_url: str,
) -> str:
    """Build prompt for design analysis.

    Args:
        design_rules: List of design rules to check against
        page_url: URL being analyzed

    Returns:
        Formatted prompt for vision analysis
    """
    # Format design rules by category
    rules_by_category: dict[str, list[str]] = {}
    for rule in design_rules:
        category = rule.get("category", "general")
        if category not in rules_by_category:
            rules_by_category[category] = []
        rule_text = f"- {rule.get('name', 'Rule')}"
        reqs = rule.get("requirements", {})
        if reqs:
            for key, val in reqs.items():
                if isinstance(val, dict):
                    severity = val.get("severity", "info")
                    if val.get("exact") is not None:
                        rule_text += f" [{key}={val['exact']}, {severity}]"
                    elif val.get("min") is not None or val.get("max") is not None:
                        rule_text += (
                            f" [{key}: {val.get('min', '')}-{val.get('max', '')}, {severity}]"
                        )
        rules_by_category[category].append(rule_text)

    rules_text = ""
    for category, rules in rules_by_category.items():
        rules_text += f"\n### {category.upper()}\n"
        rules_text += "\n".join(rules)

    return f"""Analyze this screenshot of a web page for design and UX issues.

PAGE URL: {page_url}

DESIGN STANDARDS TO CHECK:
{rules_text}

YOUR TASK:
1. Analyze the screenshot against these design standards
2. Identify specific violations and UX issues
3. Provide actionable improvement recommendations

RESPONSE FORMAT:
## Summary
<1-2 sentences summarizing overall design quality>

## Issues Found

### Critical (Must Fix)
<List critical issues that significantly impact usability or accessibility>

### Warnings (Should Fix)
<List issues that impact design quality but aren't critical>

### Suggestions (Nice to Have)
<List optional improvements>

## Specific Recommendations

<For each significant issue, provide:>
1. **Issue**: <description>
   **Location**: <where on the page>
   **Fix**: <specific actionable recommendation>

## Design Score
- Typography: X/5
- Layout: X/5
- Color/Contrast: X/5
- Accessibility: X/5
- Overall UX: X/5

Be specific and actionable. Reference actual elements visible in the screenshot."""


def _analyze_screenshot_with_vision(
    screenshot_path: Path,
    design_rules: list[dict[str, Any]],
    page_url: str,
) -> tuple[str | None, int, str | None]:
    """Analyze screenshot using Gemini Pro 3 vision via Agent Hub.

    Args:
        screenshot_path: Path to screenshot file
        design_rules: Design rules to check against
        page_url: URL being analyzed

    Returns:
        Tuple of (recommendations, issues_count, error)
    """
    from agent_hub.models import ImageContent, MessageInput, TextContent

    try:
        # Read and encode screenshot
        image_bytes = screenshot_path.read_bytes()
        image_base64 = base64.b64encode(image_bytes).decode()

        # Determine media type
        suffix = screenshot_path.suffix.lower()
        media_type = "image/png"
        if suffix in (".jpg", ".jpeg"):
            media_type = "image/jpeg"
        elif suffix == ".webp":
            media_type = "image/webp"

        # Build prompt
        prompt = _build_design_analysis_prompt(design_rules, page_url)

        # Create message with image and text content blocks
        image_content = ImageContent.from_base64(image_base64, media_type)
        text_content = TextContent(text=prompt)
        message = MessageInput(
            role="user",
            content=[image_content, text_content],
        )

        # Call Gemini Pro vision via Agent Hub
        client = get_sync_client()
        response = client.complete(
            model=GEMINI_PRO,  # gemini-3-pro-preview has vision capabilities
            messages=[message],
            project_id="summitflow",
            purpose="design_analysis",
            temperature=0.3,
        )

        recommendations = response.content

        # Count issues (rough estimate from markdown headers)
        issues_count = recommendations.count("**Issue**:")
        if issues_count == 0:
            # Count bullet points in issues sections
            issues_count = recommendations.count("- ") // 2  # Rough estimate

        return recommendations, issues_count, None

    except Exception as e:
        logger.error("vision_analysis_failed", error=str(e))
        return None, 0, str(e)


def _generate_mockup_image(
    screenshot_path: Path,
    recommendations: str,
    output_path: Path,
    page_url: str,
) -> str | None:
    """Generate a mockup image showing the improved design.

    Uses Gemini 3 Pro Image to generate a visual mockup based on the
    current screenshot and the improvement recommendations.

    Args:
        screenshot_path: Path to the current page screenshot
        recommendations: Design analysis and recommendations text
        output_path: Path to save the generated mockup image
        page_url: URL of the page being analyzed

    Returns:
        Path to the generated mockup image, or None if generation failed
    """
    try:
        # Build a prompt that describes what the improved design should look like
        prompt = f"""Generate a UI mockup image showing an IMPROVED version of a web application page.

CONTEXT:
This is a redesign of the page at: {page_url}

CURRENT ISSUES AND RECOMMENDED FIXES:
{recommendations}

REQUIREMENTS:
1. Create a high-fidelity UI mockup at 1920x1080 resolution
2. Apply ALL the recommended fixes from the analysis above
3. Maintain the overall page structure and purpose
4. Use a modern dark theme with these colors:
   - Background: #0f0a18 (deep purple-black)
   - Cards/surfaces: #1a0a2e (slightly lighter)
   - Primary accent: #00f5ff (cyan)
   - Secondary accent: #ff00ff (magenta)
   - Text: #ffffff (white) and #a0a0a0 (muted)
5. Ensure proper visual hierarchy, spacing, and contrast
6. Make text legible and UI elements clearly defined
7. Show realistic content (not lorem ipsum)

OUTPUT:
A single polished UI mockup image showing the IMPROVED design with all issues fixed."""

        # Call Gemini Image via Agent Hub
        client = get_sync_client()
        response = client.generate_image(
            prompt=prompt,
            project_id="summitflow",
            purpose="mockup_generation",
            model=GEMINI_IMAGE,
            size="1920x1080",
        )

        # Decode and save image
        image_bytes = base64.b64decode(response.image_base64)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)

        logger.info(
            "mockup_image_generated",
            output_path=str(output_path),
            size_bytes=len(image_bytes),
        )

        return str(output_path)

    except Exception as e:
        logger.error("mockup_image_generation_failed", error=str(e))
        return None


async def analyze_page_design(
    project_id: str,
    page_url: str,
    page_path: str | None = None,
) -> DesignAnalysisResult:
    """Analyze a page's design and generate improvement recommendations.

    This is the main workflow for mockup generation:
    1. Capture screenshot of the page
    2. Fetch design standards for the project
    3. Analyze screenshot against standards using Claude vision
    4. Store mockup record with screenshot and recommendations

    Args:
        project_id: Project ID
        page_url: Full URL to analyze
        page_path: Optional page path (for storage, defaults to URL path)

    Returns:
        DesignAnalysisResult with mockup details
    """
    start_time = time.monotonic()

    # Extract path from URL if not provided
    if page_path is None:
        from urllib.parse import urlparse

        parsed = urlparse(page_url)
        page_path = parsed.path or "/"

    # Step 1: Capture screenshot
    screenshot_id = f"analysis-{int(time.time())}"
    screenshot_dir = MOCKUP_BASE_DIR / project_id / screenshot_id
    screenshot_path = screenshot_dir / "screenshot.png"

    success, error = await _capture_page_screenshot(page_url, screenshot_path)
    if not success:
        return DesignAnalysisResult(
            success=False,
            error=f"Screenshot capture failed: {error}",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    # Step 2: Get design rules
    from ..storage.design_standards import get_effective_rules

    design_rules = get_effective_rules(project_id)
    if not design_rules:
        design_rules = []

    # Step 3: Analyze with vision
    recommendations, issues_count, analysis_error = _analyze_screenshot_with_vision(
        screenshot_path,
        design_rules,
        page_url,
    )

    if analysis_error:
        return DesignAnalysisResult(
            success=False,
            screenshot_path=str(screenshot_path),
            error=f"Vision analysis failed: {analysis_error}",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    # Step 4: Generate mockup image showing the improved design
    mockup_image_path = screenshot_dir / "mockup.png"

    if recommendations:
        try:
            mockup_image_path_str = _generate_mockup_image(
                screenshot_path=screenshot_path,
                recommendations=recommendations,
                output_path=mockup_image_path,
                page_url=page_url,
            )
            if mockup_image_path_str:
                mockup_image_path = Path(mockup_image_path_str)
        except Exception as e:
            logger.warning("mockup_image_generation_failed", error=str(e))

    # Step 5: Store in mockups table
    from ..storage import mockups as mockups_storage

    generation_time_ms = int((time.monotonic() - start_time) * 1000)

    # Use mockup image as primary file if available, otherwise screenshot
    primary_file = str(mockup_image_path) if mockup_image_path.exists() else str(screenshot_path)

    mockup = mockups_storage.create_mockup(
        project_id=project_id,
        name=f"Design Analysis: {page_path}",
        description=f"Automated design analysis of {page_url}",
        mockup_type="page",
        file_path=primary_file,
        page_path=page_path,
        generator="design-analyzer",
        generation_prompt=recommendations,
        generation_time_ms=generation_time_ms,
    )

    logger.info(
        "page_design_analyzed",
        project_id=project_id,
        page_url=page_url,
        mockup_id=mockup["mockup_id"],
        issues_found=issues_count,
        generation_time_ms=generation_time_ms,
        mockup_image_generated=mockup_image_path.exists(),
    )

    return DesignAnalysisResult(
        success=True,
        mockup_id=mockup["mockup_id"],
        screenshot_path=str(screenshot_path),
        mockup_image_path=str(mockup_image_path) if mockup_image_path.exists() else None,
        recommendations=recommendations,
        issues_found=issues_count,
        generation_time_ms=generation_time_ms,
    )


__all__ = [
    "DesignAnalysisResult",
    "MockupResult",
    "analyze_page_design",
    "generate_mockup",
    "generate_mockup_claude_fallback",
    "generate_mockup_gemini",
]
