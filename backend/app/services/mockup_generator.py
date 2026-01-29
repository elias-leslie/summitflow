"""Backward compatibility module for mockup_generator.

This module re-exports all public APIs from the refactored mockup_generator
package to maintain backward compatibility.
"""

from __future__ import annotations

# Re-export all public APIs from the refactored module
from .mockup_generator import (
    DesignAnalysisResult,
    MockupResult,
    analyze_page_design,
    generate_mockup,
    generate_mockup_claude_fallback,
    generate_mockup_gemini,
)

__all__ = [
    "DesignAnalysisResult",
    "MockupResult",
    "analyze_page_design",
    "generate_mockup",
    "generate_mockup_claude_fallback",
    "generate_mockup_gemini",
]
