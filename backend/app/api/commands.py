"""Command execution API — natural language commands via Agent Hub.

Provides a simple request/response interface for the PWA command panel.
Routes commands through `st complete` CLI to Agent Hub.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class CommandRequest(BaseModel):
    """Natural language command to execute."""

    text: str = Field(..., min_length=1, max_length=2000)
    project_id: str = Field(default="summitflow")
    agent: str = Field(default="coder")


class CommandResponse(BaseModel):
    """Result from command execution."""

    response: str
    success: bool


@router.post("/commands", response_model=CommandResponse)
async def execute_command(body: CommandRequest) -> CommandResponse:
    """Execute a natural language command via Agent Hub.

    Routes to `st complete --agent <agent> --project <project> --raw '<text>'`.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "st",
            "complete",
            "--agent",
            body.agent,
            "--project",
            body.project_id,
            "--raw",
            body.text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Command timed out") from exc
    except FileNotFoundError as exc:
        logger.error("st CLI not found in PATH")
        raise HTTPException(status_code=503, detail="Command service unavailable") from exc

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Command failed"
        logger.warning("st complete failed (rc=%d): %s", proc.returncode, error_msg)
        return CommandResponse(response=error_msg, success=False)

    response_text = stdout.decode().strip() if stdout else ""
    return CommandResponse(response=response_text, success=True)
