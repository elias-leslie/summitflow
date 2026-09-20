"""Compatibility import for the design_tools.services.mockup_generator public package."""

from app.owner_modules import expose_module
from app.services.design_host import configure_design

configure_design()
expose_module(__name__, "design_tools.services.mockup_generator", (
    "_templates",
    "_workflows",
    "analysis",
    "analysis.mockup_image",
    "analysis.screenshot",
    "analysis.vision",
    "models",
    "prompts",
    "renderers",
    "renderers.claude",
    "renderers.gemini",
    "revisions",
    "sprite_prompts",
    "storage_helpers",
))
