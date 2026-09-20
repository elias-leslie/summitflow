"""Compatibility import for the design_tools.services.design_asset_pipeline public package."""

from app.owner_modules import expose_module
from app.services.design_host import configure_design

configure_design()
expose_module(__name__, "design_tools.services.design_asset_pipeline")
