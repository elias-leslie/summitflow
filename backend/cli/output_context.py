"""Compatibility alias for the public ST SDK output context."""

from __future__ import annotations

import sys

from st_sdk import context as _implementation
from st_sdk.context import OutputContext as OutputContext

__all__ = ["OutputContext"]

sys.modules[__name__] = _implementation
