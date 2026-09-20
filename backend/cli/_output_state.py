"""Compatibility alias for public ST SDK output state."""

from __future__ import annotations

import sys

from st_sdk import state as _implementation
from st_sdk.state import is_compact as is_compact
from st_sdk.state import is_human as is_human
from st_sdk.state import is_progress_only as is_progress_only
from st_sdk.state import set_compact_output as set_compact_output
from st_sdk.state import set_human_output as set_human_output
from st_sdk.state import set_progress_only as set_progress_only

_human_output = _implementation._human_output
_compact_output = _implementation._compact_output
_progress_only = _implementation._progress_only

__all__ = [
    "is_compact",
    "is_human",
    "is_progress_only",
    "set_compact_output",
    "set_human_output",
    "set_progress_only",
]

sys.modules[__name__] = _implementation
