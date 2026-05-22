"""Selection-bus surface (`st selection`).

Aico's selection bus carries the user's latest cross-surface selection (DOM
node, screen region, OCR text) captured via AT-SPI/vision. That bus arrives in
Phase 2-3; Phase 1 ships honest empty stubs so the command surface and its
consumers exist now and the output contract is frozen early.

Bare payloads per docs/contracts/01-output-conventions.md: `current` →
`{kind: "empty"}`, `history` → `{items: []}`. No `{ok, data}` envelope.
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(help="Selection bus: current selection and recent history (Aico; Phase 1 stub).")


def _ctx(ctx: typer.Context) -> OutputContext:
    if ctx.obj is None:
        ctx.obj = OutputContext()
    return ctx.obj


@app.command()
def current(ctx: typer.Context) -> None:
    """Most recent captured selection. Phase 1: always empty.

    Examples: st selection current | st selection current --human
    """
    out = _ctx(ctx)
    if out.is_compact:
        print("selection:kind=empty")
    else:
        output_json({"kind": "empty"})


@app.command()
def history(
    ctx: typer.Context,
    n: Annotated[int, typer.Option("--n", "-n", help="Max selections to return (newest first)")] = 10,
) -> None:
    """Recent selections, newest first. Phase 1: always empty.

    Examples: st selection history | st selection history --n 5
    """
    out = _ctx(ctx)
    if out.is_compact:
        print("selection-history[0]{kind,text,ts}:")
    else:
        output_json({"items": []})
