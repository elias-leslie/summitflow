"""Prompt builders for mockup generation and design analysis."""

from __future__ import annotations

from typing import Any

from ._templates import ANALYSIS_RESPONSE_FORMAT, MOCKUP_TEMPLATE

MOCKUP_RESOLUTION = "1920x1080"
COLOR_BACKGROUND = "#0f0a18"
COLOR_SURFACE = "#1a0a2e"
COLOR_ACCENT_PRIMARY = "#00f5ff"
COLOR_ACCENT_SECONDARY = "#ff00ff"
COLOR_TEXT_PRIMARY = "#ffffff"
COLOR_TEXT_MUTED = "#a0a0a0"

_RULE_CATEGORIES = ("colors", "typography", "layout", "components")

_DARK_THEME_COLORS = (
    f"   - Background: {COLOR_BACKGROUND} (deep purple-black)\n"
    f"   - Cards/surfaces: {COLOR_SURFACE} (slightly lighter)\n"
    f"   - Primary accent: {COLOR_ACCENT_PRIMARY} (cyan)\n"
    f"   - Secondary accent: {COLOR_ACCENT_SECONDARY} (magenta)\n"
    f"   - Text: {COLOR_TEXT_PRIMARY} (white) and {COLOR_TEXT_MUTED} (muted)"
)


def _format_rules(rule_list: list[dict[str, Any]], max_rules: int = 3) -> str:
    """Format design rules into readable lines."""
    if not rule_list:
        return "None specified"
    return "\n".join(
        f"- {r.get('name', 'Rule')}: {r.get('value', '')}" for r in rule_list[:max_rules]
    )


def _format_requirement(key: str, val: dict[str, Any]) -> str:
    """Format a single rule requirement constraint."""
    severity = val.get("severity", "info")
    if val.get("exact") is not None:
        return f" [{key}={val['exact']}, {severity}]"
    if val.get("min") is not None or val.get("max") is not None:
        return f" [{key}: {val.get('min', '')}-{val.get('max', '')}, {severity}]"
    return ""


def _group_rules_by_category(design_rules: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group and format design rules by category."""
    result: dict[str, list[str]] = {}
    for rule in design_rules:
        category = rule.get("category", "general")
        rule_text = f"- {rule.get('name', 'Rule')}"
        for key, val in rule.get("requirements", {}).items():
            if isinstance(val, dict):
                rule_text += _format_requirement(key, val)
        result.setdefault(category, []).append(rule_text)
    return result


def build_mockup_prompt(
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> str:
    """Build the prompt for mockup generation."""
    rules = design_standard.get("rules", [])
    sections = {cat: [r for r in rules if r.get("category") == cat] for cat in _RULE_CATEGORIES}
    return MOCKUP_TEMPLATE.format(
        path=page_info.get("path", "/"),
        title=page_info.get("name", "Page"),
        description=page_info.get("description", ""),
        standard_name=design_standard.get("name", "Default"),
        colors=_format_rules(sections["colors"]),
        typography=_format_rules(sections["typography"]),
        layout=_format_rules(sections["layout"]),
        components=_format_rules(sections["components"]),
        resolution=MOCKUP_RESOLUTION,
        direction=f"\nDESIGN DIRECTION: {design_direction}" if design_direction else "",
    )


def build_design_analysis_prompt(
    design_rules: list[dict[str, Any]],
    page_url: str,
) -> str:
    """Build prompt for design analysis."""
    rules_text = "".join(
        f"\n### {cat.upper()}\n" + "\n".join(rules)
        for cat, rules in _group_rules_by_category(design_rules).items()
    )
    return (
        f"Analyze this screenshot of a web page for design and UX issues.\n\n"
        f"PAGE URL: {page_url}\n\n"
        f"DESIGN STANDARDS TO CHECK:\n{rules_text}\n\n"
        f"YOUR TASK:\n"
        f"1. Analyze the screenshot against these design standards\n"
        f"2. Identify specific violations and UX issues\n"
        f"3. Provide actionable improvement recommendations\n\n"
        f"RESPONSE FORMAT:\n{ANALYSIS_RESPONSE_FORMAT}"
    )


def build_mockup_image_prompt(
    recommendations: str,
    page_url: str,
) -> str:
    """Build prompt for generating an improved mockup image."""
    return (
        f"Generate a UI mockup image showing an IMPROVED version of a web application page.\n\n"
        f"CONTEXT:\nThis is a redesign of the page at: {page_url}\n\n"
        f"CURRENT ISSUES AND RECOMMENDED FIXES:\n{recommendations}\n\n"
        f"REQUIREMENTS:\n"
        f"1. Create a high-fidelity UI mockup at {MOCKUP_RESOLUTION} resolution\n"
        f"2. Apply ALL the recommended fixes from the analysis above\n"
        f"3. Maintain the overall page structure and purpose\n"
        f"4. Use a modern dark theme with these colors:\n{_DARK_THEME_COLORS}\n"
        f"5. Ensure proper visual hierarchy, spacing, and contrast\n"
        f"6. Make text legible and UI elements clearly defined\n"
        f"7. Show realistic content (not lorem ipsum)\n\n"
        f"OUTPUT:\nA single polished UI mockup image showing the IMPROVED design with all issues fixed."
    )


__all__ = [
    "build_design_analysis_prompt",
    "build_mockup_image_prompt",
    "build_mockup_prompt",
]
