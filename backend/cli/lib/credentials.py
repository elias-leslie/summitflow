"""Compatibility alias for public ST SDK credential loading."""

from __future__ import annotations

import sys

from st_sdk import credentials as _implementation
from st_sdk.credentials import load_credentials as load_credentials

__all__ = ["load_credentials"]

sys.modules[__name__] = _implementation
