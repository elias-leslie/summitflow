"""Prompt builders for mockup generation and design analysis."""

from __future__ import annotations

from typing import Any


def build_mockup_prompt(
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


def build_design_analysis_prompt(
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


def build_mockup_image_prompt(
    recommendations: str,
    page_url: str,
) -> str:
    """Build prompt for generating an improved mockup image.

    Args:
        recommendations: Design analysis and recommendations text
        page_url: URL of the page being analyzed

    Returns:
        Formatted prompt for image generation
    """
    return f"""Generate a UI mockup image showing an IMPROVED version of a web application page.

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


__all__ = [
    "build_design_analysis_prompt",
    "build_mockup_image_prompt",
    "build_mockup_prompt",
]
