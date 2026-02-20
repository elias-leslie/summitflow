"""Push subscription API - subscribe/unsubscribe for Web Push notifications."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.storage import push_subscriptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push-subscriptions", tags=["push-notifications"])


class SubscribeRequest(BaseModel):
    """Browser push subscription data from PushManager.subscribe()."""

    endpoint: str
    keys: SubscribeKeys


class SubscribeKeys(BaseModel):
    """ECDH key pair from the browser subscription."""

    p256dh: str
    auth: str


class UnsubscribeRequest(BaseModel):
    """Unsubscribe by endpoint."""

    endpoint: str


@router.get("/vapid-key")
async def get_vapid_key() -> dict[str, str]:
    """Return the public VAPID key for browser subscription."""
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Web Push not configured")
    return {"public_key": settings.vapid_public_key}


@router.post("")
async def subscribe(req: SubscribeRequest) -> dict[str, str]:
    """Save a push subscription from the browser."""
    sub = await asyncio.to_thread(
        push_subscriptions.save_subscription,
        endpoint=req.endpoint,
        p256dh_key=req.keys.p256dh,
        auth_key=req.keys.auth,
    )
    logger.info("Push subscription saved: %s", sub.get("id"))
    return {"status": "subscribed", "id": sub.get("id", "")}


@router.delete("")
async def unsubscribe(req: UnsubscribeRequest) -> dict[str, str]:
    """Remove a push subscription."""
    deleted = await asyncio.to_thread(
        push_subscriptions.delete_subscription,
        endpoint=req.endpoint,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "unsubscribed"}
