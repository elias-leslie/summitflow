"""Terminal WebSocket API for PTY sessions.

Provides WebSocket endpoints for terminal access:
- /ws/terminal/{session_id} - Connect to a terminal session

Uses tmux for session persistence so terminals survive disconnects.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import termios
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..logging_config import get_logger
from ..services import lifecycle
from ..storage import terminal as terminal_store

logger = get_logger(__name__)
router = APIRouter()

# Active terminal sessions: session_id -> master_fd
_sessions: dict[str, dict[str, Any]] = {}


def _create_tmux_session(session_id: str, working_dir: str | None = None) -> str:
    """Create or attach to a tmux session.

    Args:
        session_id: Unique session identifier
        working_dir: Optional working directory to start in

    Returns:
        tmux session name
    """
    session_name = f"summitflow-{session_id}"

    # Check if session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
    )

    if result.returncode != 0:
        # Create new session with optional working directory
        cmd = ["tmux", "new-session", "-d", "-s", session_name, "-x", "120", "-y", "30"]
        if working_dir:
            cmd.extend(["-c", working_dir])
        subprocess.run(cmd, capture_output=True)

        # Disable mouse mode so xterm.js handles selection natively
        subprocess.run(
            ["tmux", "set-option", "-t", session_name, "mouse", "off"],
            capture_output=True,
        )
        logger.info("tmux_session_created", session=session_name, working_dir=working_dir)
    else:
        # Ensure mouse is off for existing sessions too
        subprocess.run(
            ["tmux", "set-option", "-t", session_name, "mouse", "off"],
            capture_output=True,
        )
        logger.info("tmux_session_attached", session=session_name)

    return session_name


def _spawn_pty_for_tmux(session_name: str) -> tuple[int, int]:
    """Spawn a PTY attached to a tmux session.

    Args:
        session_name: tmux session name

    Returns:
        Tuple of (master_fd, pid)
    """
    # Fork a PTY
    pid, master_fd = pty.fork()

    if pid == 0:
        # Child process - set TERM and attach to tmux
        os.environ["TERM"] = "xterm-256color"
        os.execvp("tmux", ["tmux", "attach-session", "-t", session_name])
    else:
        # Parent process - configure the master FD
        # Set non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        return master_fd, pid


def _resize_pty(master_fd: int, cols: int, rows: int) -> None:
    """Resize a PTY.

    Args:
        master_fd: Master file descriptor
        cols: Number of columns
        rows: Number of rows
    """
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)


@router.websocket("/ws/terminal/{session_id}")
async def terminal_websocket(
    websocket: WebSocket,
    session_id: str,
    working_dir: str | None = Query(None),
) -> None:
    """WebSocket endpoint for terminal sessions.

    Protocol:
    - Text messages: Input to terminal
    - Binary messages starting with 'r': Resize event (JSON: {cols, rows})
    - Server sends output as text messages

    Args:
        websocket: WebSocket connection
        session_id: Terminal session identifier
        working_dir: Optional working directory for new sessions
    """
    await websocket.accept()
    logger.info("terminal_connected", session_id=session_id, working_dir=working_dir)

    master_fd: int | None = None
    pid: int | None = None

    try:
        # Check if session exists in DB and ensure tmux is alive
        # This will recreate tmux if the DB record exists but tmux died
        try:
            is_alive = lifecycle.ensure_session_alive(session_id)
        except Exception as e:
            # Handle invalid session IDs (e.g., non-UUID format)
            logger.warning("terminal_session_invalid", session_id=session_id, error=str(e))
            is_alive = False

        if not is_alive:
            # Session doesn't exist in DB or couldn't be resurrected
            logger.warning("terminal_session_dead", session_id=session_id)
            await websocket.close(
                code=4000,
                reason='{"error": "session_dead", "message": "Session not found or could not be restored"}',
            )
            return

        # Touch session to update last_accessed_at
        terminal_store.touch_session(session_id)

        # Get session info for working directory (if we need to recreate)
        session = terminal_store.get_session(session_id)
        session_working_dir = session.get("working_dir") if session else working_dir

        # Create or attach to tmux session (should exist now due to ensure_session_alive)
        session_name = _create_tmux_session(session_id, session_working_dir)

        # Spawn PTY for tmux
        master_fd, pid = _spawn_pty_for_tmux(session_name)

        # Store session info
        _sessions[session_id] = {
            "master_fd": master_fd,
            "pid": pid,
            "session_name": session_name,
        }

        # Start output reader task
        output_task = asyncio.create_task(_read_output(websocket, master_fd))

        # Read input from WebSocket
        try:
            while True:
                message = await websocket.receive()

                if message["type"] == "websocket.disconnect":
                    break

                if "text" in message:
                    text = message["text"]

                    # Check for resize command (JSON starting with {"resize":)
                    if text.startswith('{"resize":'):
                        try:
                            data = json.loads(text)
                            resize = data.get("resize", {})
                            cols = resize.get("cols", 120)
                            rows = resize.get("rows", 30)
                            _resize_pty(master_fd, cols, rows)
                            logger.info(
                                "terminal_resized",
                                session_id=session_id,
                                cols=cols,
                                rows=rows,
                            )
                        except json.JSONDecodeError:
                            pass
                    else:
                        # Regular input - write to PTY
                        os.write(master_fd, text.encode("utf-8"))

                elif "bytes" in message:
                    # Binary data - write directly
                    os.write(master_fd, message["bytes"])

        except WebSocketDisconnect:
            logger.info("terminal_disconnected", session_id=session_id)

        finally:
            output_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await output_task

    except Exception as e:
        logger.error("terminal_error", session_id=session_id, error=str(e))
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason=str(e))

    finally:
        # Clean up PTY but keep tmux session
        if master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(master_fd)

        _sessions.pop(session_id, None)

        logger.info("terminal_cleanup_complete", session_id=session_id)


async def _read_output(websocket: WebSocket, master_fd: int) -> None:
    """Read output from PTY and send to WebSocket.

    Args:
        websocket: WebSocket connection
        master_fd: Master file descriptor
    """
    loop = asyncio.get_event_loop()

    try:
        while True:
            # Use select to wait for data with timeout
            ready, _, _ = await loop.run_in_executor(
                None,
                lambda: select.select([master_fd], [], [], 0.1),
            )

            if ready:
                try:
                    output = os.read(master_fd, 4096)
                    if output:
                        await websocket.send_text(output.decode("utf-8", errors="replace"))
                except OSError:
                    break
            else:
                await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("terminal_output_error", error=str(e))
