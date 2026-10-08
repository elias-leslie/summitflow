"""Exact owner title command, independent of fleet or native TUI identity."""

from __future__ import annotations

from typing import Annotated

import typer

from ..lib.root_title import RootSurface, title_root
from ..lib.usage import usage
from ..output import output_error, output_json


@usage(
    surface="st.sessions.title",
    cmd='st sessions title ROOT "Project · Focus" [--surface aico|a-term]',
    when="rename one exact retained owner root using its current generation",
    precautions=("Supply a non-secret control-free single-line label of at most 160 UTF-8 bytes. Only the owner's existing session metadata retains it; output contains no label.",),
    tier="reference",
)
def title(
    root: Annotated[str, typer.Argument(help="Exact retained owner request/root ID")],
    label: Annotated[str, typer.Argument(help="Non-secret control-free single-line label, at most 160 UTF-8 bytes")],
    surface: Annotated[RootSurface, typer.Option(help="Local root owner, matching the create surface")] = "aico",
) -> None:
    """Rename an exact running root through its generation-fenced owner endpoint."""
    try:
        result = title_root(root, label, surface=surface)
    except ValueError as error:
        # Click's BadParameter renders argv; never echo the supplied label on failure.
        output_error(str(error))
        raise typer.Exit(1) from None
    output_json(result)
