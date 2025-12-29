"""Terminal session lifecycle management.

Provides atomic operations for terminal session lifecycle:
- Atomic create (DB + tmux, rollback on failure)
- Atomic delete (tmux kill + DB delete)
- Session resurrection (recreate tmux if DB record exists)
- Startup reconciliation (sync DB ↔ tmux state)
- Abandoned session cleanup

The database is the source of truth; tmux is the implementation detail.
"""

from __future__ import annotations

import subprocess

from ..logging_config import get_logger
from ..storage import terminal as terminal_store

logger = get_logger(__name__)


class TmuxError(Exception):
    """Error interacting with tmux."""


def _get_tmux_session_name(session_id: str) -> str:
    """Convert session ID to tmux session name.

    Args:
        session_id: Session UUID

    Returns:
        tmux session name (e.g., summitflow-abc123)
    """
    return f"summitflow-{session_id}"


def _tmux_session_exists(session_id: str) -> bool:
    """Check if a tmux session exists.

    Args:
        session_id: Session UUID

    Returns:
        True if tmux session exists
    """
    session_name = _get_tmux_session_name(session_id)
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
    )
    return result.returncode == 0


def _create_tmux_session(session_id: str, working_dir: str | None = None) -> None:
    """Create a tmux session.

    Args:
        session_id: Session UUID
        working_dir: Optional working directory

    Raises:
        TmuxError: If tmux session creation fails
    """
    session_name = _get_tmux_session_name(session_id)

    # Check if already exists
    if _tmux_session_exists(session_id):
        logger.info("tmux_session_exists", session=session_name)
        return

    # Create new session
    cmd = ["tmux", "new-session", "-d", "-s", session_name, "-x", "120", "-y", "30"]
    if working_dir:
        cmd.extend(["-c", working_dir])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(
            "tmux_create_failed",
            session=session_name,
            error=result.stderr,
        )
        raise TmuxError(f"Failed to create tmux session: {result.stderr}")

    logger.info("tmux_session_created", session=session_name, working_dir=working_dir)


def _kill_tmux_session(session_id: str, ignore_missing: bool = True) -> bool:
    """Kill a tmux session.

    Args:
        session_id: Session UUID
        ignore_missing: Don't raise error if session doesn't exist

    Returns:
        True if session was killed, False if it didn't exist

    Raises:
        TmuxError: If kill fails (and ignore_missing is False)
    """
    session_name = _get_tmux_session_name(session_id)

    result = subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if ignore_missing and "session not found" in result.stderr.lower():
            logger.info("tmux_session_not_found", session=session_name)
            return False
        if not ignore_missing:
            raise TmuxError(f"Failed to kill tmux session: {result.stderr}")
        return False

    logger.info("tmux_session_killed", session=session_name)
    return True


def _list_tmux_sessions() -> set[str]:
    """List all summitflow tmux sessions.

    Returns:
        Set of session IDs (without summitflow- prefix)
    """
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )

    sessions = set()
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if line.startswith("summitflow-"):
                session_id = line.replace("summitflow-", "")
                sessions.add(session_id)

    return sessions


def create_session(
    name: str,
    project_id: str | None = None,
    working_dir: str | None = None,
    user_id: str | None = None,
) -> str:
    """Create a new terminal session atomically.

    Creates DB record first, then tmux session. If tmux creation fails,
    rolls back the DB record.

    Args:
        name: Display name for the session
        project_id: Optional project ID for context
        working_dir: Initial working directory
        user_id: Optional user ID (for future auth)

    Returns:
        Server-generated session UUID

    Raises:
        TmuxError: If tmux session creation fails (after rollback)
    """
    # Step 1: Create DB record
    session_id = terminal_store.create_session(
        name=name,
        project_id=project_id,
        working_dir=working_dir,
        user_id=user_id,
    )

    # Step 2: Create tmux session
    try:
        _create_tmux_session(session_id, working_dir)
    except TmuxError as e:
        # Rollback: delete DB record
        logger.error(
            "tmux_create_failed_rolling_back",
            session_id=session_id,
            error=str(e),
        )
        terminal_store.delete_session(session_id)
        raise

    logger.info(
        "session_created",
        session_id=session_id,
        name=name,
        project_id=project_id,
    )

    return session_id


def delete_session(session_id: str) -> bool:
    """Delete a terminal session.

    Kills tmux session first, then deletes DB record.
    Idempotent - returns True even if session didn't exist.

    Args:
        session_id: Session UUID

    Returns:
        True (always succeeds, idempotent)
    """
    # Step 1: Kill tmux session (ignore if missing)
    _kill_tmux_session(session_id, ignore_missing=True)

    # Step 2: Delete DB record
    deleted = terminal_store.delete_session(session_id)

    if deleted:
        logger.info("session_deleted", session_id=session_id)
    else:
        logger.info("session_not_found_for_delete", session_id=session_id)

    return True


def ensure_session_alive(session_id: str) -> bool:
    """Ensure a session is alive, recreating tmux if necessary.

    Called on WebSocket connect. If tmux session died but DB record
    exists, attempts to recreate the tmux session.

    Args:
        session_id: Session UUID

    Returns:
        True if session is alive (or was successfully resurrected)
        False if session doesn't exist in DB or resurrection failed
    """
    # Check DB record exists
    session = terminal_store.get_session(session_id)
    if not session:
        logger.warning("ensure_alive_no_db_record", session_id=session_id)
        return False

    # Check tmux session
    if _tmux_session_exists(session_id):
        # Ensure DB says it's alive
        if not session["is_alive"]:
            terminal_store.update_session(session_id, is_alive=True)
            logger.info("session_marked_alive", session_id=session_id)
        return True

    # tmux died - try to recreate
    logger.info("session_resurrection_attempt", session_id=session_id)

    try:
        _create_tmux_session(session_id, session.get("working_dir"))
        terminal_store.update_session(session_id, is_alive=True)
        logger.info("session_resurrected", session_id=session_id)
        return True
    except TmuxError as e:
        logger.error(
            "session_resurrection_failed",
            session_id=session_id,
            error=str(e),
        )
        terminal_store.mark_dead(session_id)
        return False


def reconcile_on_startup() -> dict[str, int]:
    """Reconcile DB with tmux state on server startup.

    Syncs the database with the actual tmux session state:
    - Sessions in DB but not tmux: mark as dead
    - Sessions in DB and tmux: mark as alive

    Returns:
        Stats dict with counts of sessions processed
    """
    logger.info("reconciliation_starting")

    # Get all DB sessions (including dead ones)
    db_sessions = terminal_store.list_sessions(include_dead=True)

    # Get all tmux sessions
    tmux_sessions = _list_tmux_sessions()

    stats = {
        "total_db_sessions": len(db_sessions),
        "total_tmux_sessions": len(tmux_sessions),
        "marked_alive": 0,
        "marked_dead": 0,
    }

    for session in db_sessions:
        session_id = session["id"]

        if session_id in tmux_sessions:
            # Session exists in both - ensure marked alive
            if not session["is_alive"]:
                terminal_store.update_session(session_id, is_alive=True)
                stats["marked_alive"] += 1
                logger.info("reconcile_marked_alive", session_id=session_id)
        else:
            # Session in DB but not tmux - mark dead
            if session["is_alive"]:
                terminal_store.mark_dead(session_id)
                stats["marked_dead"] += 1
                logger.info("reconcile_marked_dead", session_id=session_id)

    logger.info("reconciliation_complete", **stats)

    return stats


def cleanup_abandoned(days: int = 30) -> int:
    """Clean up abandoned sessions.

    Deletes sessions not accessed in N days (both DB and tmux).

    Args:
        days: Days since last access threshold

    Returns:
        Number of sessions cleaned up
    """
    logger.info("cleanup_starting", older_than_days=days)

    orphaned = terminal_store.list_orphaned(older_than_days=days)

    count = 0
    for session in orphaned:
        session_id = session["id"]
        delete_session(session_id)
        count += 1
        logger.info(
            "orphaned_session_cleaned",
            session_id=session_id,
            last_accessed=session.get("last_accessed_at"),
        )

    logger.info("cleanup_complete", sessions_cleaned=count)

    return count
