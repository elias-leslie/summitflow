"""Compatibility alias for public ST SDK detail-file helpers."""

from __future__ import annotations

import sys

from st_sdk import details as _implementation
from st_sdk.details import current_root as current_root
from st_sdk.details import detail_path as detail_path
from st_sdk.details import display_path as display_path
from st_sdk.details import emit_result_or_details as emit_result_or_details
from st_sdk.details import result_output as result_output
from st_sdk.details import strip_ansi as strip_ansi
from st_sdk.details import summary_hint as summary_hint
from st_sdk.details import write_details as write_details

__all__ = [
    "current_root",
    "detail_path",
    "display_path",
    "emit_result_or_details",
    "result_output",
    "strip_ansi",
    "summary_hint",
    "write_details",
]

sys.modules[__name__] = _implementation
