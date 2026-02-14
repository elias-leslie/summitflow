"""Notification delivery services.

Routes notifications to external channels (ntfy push, future: Web Push).
"""

from __future__ import annotations

from .delivery import deliver
from .ntfy import send as send_ntfy

__all__ = ["deliver", "send_ntfy"]
