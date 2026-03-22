"""Two-pass confirmation tokens for destructive CLI operations.

Every destructive command follows the same pattern:
  1. First run (no --confirm): show blast radius, generate token, exit
  2. Second run (--confirm TOKEN): validate token, execute, consume token

The token is a short random hex string stored in a temp file. It is single-use
and scoped to a specific command + target. This forces every caller — human or
agent — to see the preview before executing.
"""

from __future__ import annotations

import uuid
from pathlib import Path

_TOKENS_DIR = Path.home() / ".local" / "share" / "st" / "confirm-tokens"


def _token_path(command_key: str) -> Path:
    safe_key = command_key.replace("/", "_").replace(" ", "_")
    return _TOKENS_DIR / safe_key


def generate_token(command_key: str) -> str:
    """Generate a single-use confirm token and persist it.

    Returns the 8-character hex token.
    """
    _TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    _token_path(command_key).write_text(token, encoding="utf-8")
    return token


def validate_token(command_key: str, token: str) -> bool:
    """Check token validity and consume it (single-use).

    Returns True if the token matches. The token file is always deleted
    on a match so it cannot be reused.
    """
    path = _token_path(command_key)
    if not path.exists():
        return False
    stored = path.read_text(encoding="utf-8").strip()
    if stored != token.strip():
        return False
    path.unlink(missing_ok=True)
    return True


def confirm_gate(
    command_key: str,
    confirm: str | None,
    preview_lines: list[str],
    preview_cmd: str,
) -> None:
    """Two-pass confirm gate for destructive commands.

    Call this before executing the destructive action. It either:
    - Shows the preview and exits (when confirm is None), or
    - Validates the token and exits with error (when token is invalid), or
    - Returns normally (when token is valid) — proceed with the action.
    """
    import typer

    from ..output import output_error

    if confirm is None:
        token = generate_token(command_key)
        print(format_preview(preview_cmd, preview_lines, token))
        raise typer.Exit(0)

    if not validate_token(command_key, confirm):
        output_error(
            "Invalid or expired confirm token.\n"
            "  Run the command without --confirm to preview and get a new token."
        )
        raise typer.Exit(1)


def format_preview(command_hint: str, lines: list[str], token: str) -> str:
    """Format a standard preview block with confirm hint.

    Args:
        command_hint: The full command to re-run with --confirm, e.g.
                      ``"st abandon task-123"``
        lines: Preview lines describing what will happen.
        token: The generated confirm token.

    Returns:
        Formatted multi-line string ready to print.
    """
    body = "\n".join(f"  {line}" for line in lines)
    return (
        f"\n{body}\n\n"
        f"To confirm, run:\n"
        f"  {command_hint} --confirm {token}\n"
    )
