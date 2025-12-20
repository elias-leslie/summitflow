"""
Permission Manager for Roundtable Tool Execution.

Manages pending permission requests for write tools, providing async waiting
with timeout support. Permission callbacks from SDK hooks create requests here,
and the frontend resolves them via the API endpoint.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PendingPermission:
    """A pending permission request awaiting user approval."""

    id: str
    session_id: str
    tool_name: str
    tool_args: dict
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: Optional[bool] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class PermissionManager:
    """
    Manages pending permission requests with async waiting and timeout.

    Usage:
        # In SDK hook callback:
        approved = await permission_manager.request_permission(
            session_id, tool_name, tool_args
        )

        # In API endpoint (frontend calls this):
        permission_manager.resolve(permission_id, approved=True)
    """

    def __init__(self, timeout: float = 60.0):
        """
        Initialize the permission manager.

        Args:
            timeout: Seconds to wait for permission resolution before auto-deny.
        """
        self._pending: dict[str, PendingPermission] = {}
        self._timeout = timeout

    async def request_permission(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict,
    ) -> bool:
        """
        Create a permission request and wait for resolution.

        Args:
            session_id: The roundtable session ID.
            tool_name: Name of the tool requesting permission.
            tool_args: Arguments passed to the tool.

        Returns:
            True if approved, False if denied or timed out.
        """
        permission = PendingPermission(
            id=f"perm-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        self._pending[permission.id] = permission

        logger.info(
            "Permission request created: id=%s session=%s tool=%s",
            permission.id,
            session_id,
            tool_name,
        )

        try:
            await asyncio.wait_for(
                permission.event.wait(),
                timeout=self._timeout,
            )
            logger.info(
                "Permission resolved: id=%s approved=%s",
                permission.id,
                permission.approved,
            )
            return permission.approved or False
        except asyncio.TimeoutError:
            logger.warning(
                "Permission timed out: id=%s session=%s tool=%s",
                permission.id,
                session_id,
                tool_name,
            )
            return False
        finally:
            self._pending.pop(permission.id, None)

    def resolve(self, permission_id: str, approved: bool) -> bool:
        """
        Resolve a pending permission request.

        Args:
            permission_id: The ID of the permission to resolve.
            approved: Whether to approve (True) or deny (False).

        Returns:
            True if permission was found and resolved, False otherwise.
        """
        permission = self._pending.get(permission_id)
        if permission is None:
            logger.warning(
                "Permission not found or expired: id=%s",
                permission_id,
            )
            return False

        permission.approved = approved
        permission.event.set()
        return True

    def get_pending(self, permission_id: str) -> Optional[PendingPermission]:
        """
        Get a pending permission by ID.

        Args:
            permission_id: The ID of the permission to retrieve.

        Returns:
            The PendingPermission if found, None otherwise.
        """
        return self._pending.get(permission_id)

    def get_session_pending(self, session_id: str) -> list[PendingPermission]:
        """
        Get all pending permissions for a session.

        Args:
            session_id: The session ID to filter by.

        Returns:
            List of pending permissions for the session.
        """
        return [p for p in self._pending.values() if p.session_id == session_id]

    def deny_session_pending(self, session_id: str) -> int:
        """
        Auto-deny all pending permissions for a session.

        Used when client disconnects to unblock waiting hooks.

        Args:
            session_id: The session ID to deny permissions for.

        Returns:
            Number of permissions denied.
        """
        pending = self.get_session_pending(session_id)
        for permission in pending:
            permission.approved = False
            permission.event.set()
            logger.info(
                "Permission auto-denied (disconnect): id=%s tool=%s",
                permission.id,
                permission.tool_name,
            )
        return len(pending)


# Global instance for use across the application
permission_manager = PermissionManager()
