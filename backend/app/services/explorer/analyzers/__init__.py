"""Compatibility import for the code_intelligence.analyzers public package."""

from app.owner_modules import expose_module
from app.services.code_intelligence_host import configure_code_intelligence

configure_code_intelligence()
expose_module(__name__, "code_intelligence.analyzers", (
    "_helpers",
    "_python_extractor",
    "_ts_extractor",
    "ast_analyzer",
    "symbol_extractor",
    "symbol_types",
))
