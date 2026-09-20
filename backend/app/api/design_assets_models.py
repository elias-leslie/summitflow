"""Compatibility import for the design_tools.schemas.design_assets_models public package."""

from app.owner_modules import expose_module
from app.services.design_host import configure_design

configure_design()
expose_module(__name__, "design_tools.schemas.design_assets_models")
