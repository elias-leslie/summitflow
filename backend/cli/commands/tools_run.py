"""Public resource admission for external tool commands."""

from __future__ import annotations

from typing import Annotated

import typer

from app.utils.heavy_work import HeavyWorkError, heavy_work

from ..lib.usage import usage
from ..output import output_error


@usage(
    surface="st.tools.run",
    cmd="st tools run --label TEXT -- <argv...>",
    when="run an external tool through shared heavy-work admission",
    precautions=(
        "Resource admission only; label is public, so omit secrets. Child argv runs without a shell and inherits admission.",
        "Not for long disk/network jobs (restores, bulk downloads): run them throttled outside the lane, see docs/transient-heavy-work.md.",
    ),
)
def run(
    command: Annotated[list[str], typer.Argument(help="Executable and arguments; put -- before the executable.")],
    label: Annotated[str, typer.Option("--label", help="Public operation label; omit secrets.")],
) -> None:
    """Wait for shared resource admission, then run a tool with its normal output."""
    try:
        with heavy_work(label, work_class="heavy") as work:
            result = work.run(command, check=False)
    except HeavyWorkError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    except OSError as exc:
        output_error("Tool could not be started.")
        raise typer.Exit(127 if isinstance(exc, FileNotFoundError) else 126) from None
    raise typer.Exit(result.returncode)
