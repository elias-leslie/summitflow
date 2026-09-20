"""Compatibility alias for public ST SDK output primitives."""

from __future__ import annotations

import sys

from st_sdk import output as _implementation
from st_sdk.output import handle_api_error as handle_api_error
from st_sdk.output import output_error as output_error
from st_sdk.output import output_json as output_json
from st_sdk.output import output_success as output_success
from st_sdk.output import output_warning as output_warning
from st_sdk.output import require_explicit_project as require_explicit_project

__all__ = [
    "handle_api_error",
    "output_error",
    "output_json",
    "output_success",
    "output_warning",
    "require_explicit_project",
]

sys.modules[__name__] = _implementation
