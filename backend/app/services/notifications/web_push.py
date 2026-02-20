"""Web Push notification sender.

Sends push notifications via the Web Push protocol using VAPID authentication.
Never raises — logs errors and returns False.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush

from app.config import settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """Check if VAPID keys are configured."""
    return bool(settings.vapid_public_key and settings.vapid_private_key)


async def send(
    subscription: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    """Send a push notification to a single subscription.

    Never raises — logs errors and returns False.

    Args:
        subscription: Push subscription dict with endpoint, p256dh_key, auth_key.
        payload: Notification payload (title, body, url, etc.).

    Returns:
        True if sent successfully, False otherwise.
    """
    if not _is_configured():
        logger.debug("Web Push not configured (missing VAPID keys)")
        return False

    subscription_info = {
        "endpoint": subscription["endpoint"],
        "keys": {
            "p256dh": subscription["p256dh_key"],
            "auth": subscription["auth_key"],
        },
    }

    vapid_claims = {
        "sub": settings.vapid_subject,
    }

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims=vapid_claims,
        )
        return True
    except WebPushException as e:
        # 410 Gone = subscription expired, caller should clean up
        if hasattr(e, "response") and e.response is not None and e.response.status_code == 410:
            logger.info("Push subscription expired: %s", subscription.get("endpoint", "")[:50])
        else:
            logger.exception("Failed to send web push notification")
        return False
    except Exception:
        logger.exception("Unexpected error sending web push notification")
        return False
