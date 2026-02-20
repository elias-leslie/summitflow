"""Notification delivery services.

Routes notifications to Web Push via the delivery module.
"""

from __future__ import annotations

from .delivery import deliver

__all__ = ["deliver"]
