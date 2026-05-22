"""Selection-bus surface (`st selection`).

Aico's selection bus carries the user's latest cross-surface selection (DOM
node, screen region, OCR text). The bus lives in Aico's sidecar; these commands
read it over loopback HTTP. A capture is best-effort context an agent pulls
speculatively, so a sidecar that is down or empty surfaces as an honest empty
selection rather than an error.

Bare payloads per docs/contracts/01-output-conventions.md: `current` →
`{kind: "empty"}` or the selection record; `history` → `{items: [...], count}`.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

import httpx
import typer

from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(help="Selection bus: current selection and recent history (Aico).")


def _sidecar_base() -> str:
    host = os.environ.get("AICO_SIDECAR_HOST", "127.0.0.1")
    port = os.environ.get("AICO_SIDECAR_PORT", "8005")
    return f"http://{host}:{port}"


def _sidecar_get(path: str) -> dict[str, Any]:
    """GET JSON from the Aico sidecar. Any failure (sidecar down, bad response)
    returns `{}` so a speculative `st selection current` never breaks a flow."""
    try:
        resp = httpx.get(f"{_sidecar_base()}{path}", timeout=2.0)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


def _ctx(ctx: typer.Context) -> OutputContext:
    if ctx.obj is None:
        ctx.obj = OutputContext()
    return ctx.obj


def _clip(text: str | None, n: int) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


@app.command()
def current(ctx: typer.Context) -> None:
    """Most recent captured selection (`{kind: "empty"}` when none).

    Examples: st selection current | st selection current --human
    """
    out = _ctx(ctx)
    data = _sidecar_get("/selection/current")
    kind = data.get("kind", "empty")
    if not data or kind == "empty":
        if out.is_compact:
            print("selection:kind=empty")
        else:
            output_json({"kind": "empty"})
        return
    if out.is_compact:
        print(
            f"selection:kind={kind} captured_at={data.get('captured_at', '')} "
            f'snippet="{_clip(data.get("snippet"), 80)}"'
        )
    else:
        output_json(data)


@app.command()
def history(
    ctx: typer.Context,
    n: Annotated[
        int, typer.Option("--n", "-n", help="Max selections to return (newest first)")
    ] = 10,
) -> None:
    """Recent selections, newest first.

    Examples: st selection history | st selection history --n 5
    """
    out = _ctx(ctx)
    data = _sidecar_get(f"/selection/history?n={n}")
    items = data.get("items", [])
    count = data.get("count", len(items))
    if out.is_compact:
        print(f"selection-history[{count}]{{kind,captured_at,snippet}}:")
        for it in items:
            print(
                f'  {it.get("kind")} {it.get("captured_at", "")} "{_clip(it.get("snippet"), 60)}"'
            )
    else:
        output_json({"items": items, "count": count})
