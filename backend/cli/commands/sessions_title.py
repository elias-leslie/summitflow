"""Compatibility alias: `st sessions title` forwards to the owner's `st aico root title`."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

from .. import extensions
from ..lib.usage import usage
from ..output import output_error

RootSurface = Literal["aico", "a-term"]


@usage(
    surface="st.sessions.title",
    cmd='st sessions title ROOT "Project · Focus" [--surface aico|a-term]',
    when="compatibility alias of st aico root title for one exact retained owner root",
    precautions=("Supply a non-secret control-free single-line label of at most 160 UTF-8 bytes. Only the owner's existing session metadata retains it; output contains no label.",),
    tier="reference",
)
def title(
    root: Annotated[str, typer.Argument(help="Exact retained owner request/root ID")],
    label: Annotated[str, typer.Argument(help="Non-secret control-free single-line label, at most 160 UTF-8 bytes")],
    surface: Annotated[RootSurface, typer.Option(help="Local root owner, matching the create surface")] = "aico",
) -> None:
    """Alias of `st aico root title`: the owner validates, fences and reports the receipt."""
    record = next((row for row in extensions.load_extensions(set()).records
                   if row.binding is not None and row.binding.namespace == "aico"), None)
    if record is None or record.status != "unverified":
        output_error("Aico owner extension unavailable")
        raise typer.Exit(1)
    # `--` keeps a label that begins with '-' positional in the owner parser.
    raise typer.Exit(extensions.dispatch_extension(
        record, ["root", "title", "--surface", surface, "--", root, label],
        context=extensions.extension_context()))
