"""Compatibility import for the code_intelligence.precision.sections public package."""

from app.owner_modules import expose_module
from app.services.code_intelligence_host import configure_code_intelligence

configure_code_intelligence()
expose_module(__name__, "code_intelligence.precision.sections")
