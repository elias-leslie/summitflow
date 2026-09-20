"""Compatibility alias for public ST SDK HTTP primitives."""

from __future__ import annotations

import sys

from st_sdk import http as _implementation
from st_sdk.http import APIError as APIError
from st_sdk.http import BaseHTTPClient as BaseHTTPClient

__all__ = ["APIError", "BaseHTTPClient"]

sys.modules[__name__] = _implementation
