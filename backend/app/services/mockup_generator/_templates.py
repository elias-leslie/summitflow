"""Static prompt templates for mockup generation and design analysis."""

from __future__ import annotations

MOCKUP_TEMPLATE = """\
Generate a high-fidelity UI mockup for a web application page.

PAGE CONTEXT:
- Path: {path}
- Title: {title}
- Description: {description}

DESIGN STANDARD: {standard_name}

COLOR PALETTE:
{colors}

TYPOGRAPHY:
{typography}

LAYOUT RULES:
{layout}

COMPONENT PATTERNS:
{components}

REQUIREMENTS:
1. Create a complete, professional UI mockup at {resolution} resolution
2. Use a dark theme with the specified color palette
3. Include realistic content (not lorem ipsum)
4. Show proper spacing, alignment, and visual hierarchy
5. Include navigation, content area, and any relevant UI elements
6. Text should be legible and rendered clearly
{direction}
Output a single image that represents the target design state for this page."""

ANALYSIS_RESPONSE_FORMAT = """\
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
