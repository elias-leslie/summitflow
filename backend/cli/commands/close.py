"""Close command for st CLI — DEPRECATED.

This command previously deleted branches without merging, causing data loss.
It has been replaced by:
  - st done: merge and complete (keeps work)
  - st abandon: discard and abandon (throws away work)
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..output import output_error

app = typer.Typer(help="[DEPRECATED] Use 'st done' or 'st abandon' instead")


@app.command(name="close")
def close_command(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="(ignored, command is deprecated)"),
    ] = False,
) -> None:
    """DEPRECATED: Use 'st done' or 'st abandon' instead.

    This command was removed because it marked tasks as 'completed'
    while deleting branches without merging — causing silent data loss.

    Use instead:
        st done <task-id>       Merge branches and complete (keeps your work)
        st abandon <task-id>    Discard branches and abandon (throws away work)
    """
    output_error(
        "st close is deprecated (caused data loss by deleting unmerged branches).\n"
        "\n"
        "Use instead:\n"
        f"  st done {task_id}       # merge and complete (keeps work)\n"
        f"  st abandon {task_id}    # discard and abandon (throws away work)"
    )
    raise typer.Exit(1)
