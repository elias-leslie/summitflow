"""Compatibility import for the design_tools.storage.mockups public package."""

from app.owner_modules import expose_module
from app.services.design_host import configure_design

configure_design()
expose_module(__name__, "design_tools.storage.mockups", (
    "comments",
    "core",
    "history",
    "queries",
    "updates",
))
