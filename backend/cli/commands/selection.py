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

import json
import os
import sys
from typing import Annotated, Any

import httpx
import typer

from ..output import output_error, output_json
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


def _sidecar_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to the Aico sidecar. Unlike the best-effort reads, an explicit
    send must surface failures, so this raises on transport/HTTP errors."""
    resp = httpx.post(f"{_sidecar_base()}{path}", json=payload, timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


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


@app.command()
def send(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="Selection kind: dom | a11y | region")],
    snippet: Annotated[
        str | None, typer.Option("--snippet", "-s", help="Snippet text or file path")
    ] = None,
    stdin: Annotated[bool, typer.Option("--stdin", help="Read the snippet from stdin")] = False,
    meta: Annotated[
        str | None, typer.Option("--meta", help="Extra meta as a JSON object")
    ] = None,
    no_deliver: Annotated[
        bool, typer.Option("--no-deliver", help="Store only; do not push to the active widget")
    ] = False,
) -> None:
    """Write a capture to the selection bus — the CLI/desktop source.

    Captures come from `st ui`; this verb puts one on the bus. Default delivers
    to the active Aico widget (the explicit-gesture path); --no-deliver stores
    only (harvested later via the hotkey). The kind is validated by the sidecar.

    Examples:
      st ui shot -w aico -o /tmp/x.png && st selection send region -s /tmp/x.png
      st ui ocr aico | st selection send region --stdin
    """
    out = _ctx(ctx)
    text = (sys.stdin.read() if stdin else (snippet or "")).strip()
    if not text:
        output_error("nothing to send (provide --snippet or --stdin)")
        raise typer.Exit(1)
    extra: dict[str, Any] = {}
    if meta:
        try:
            parsed = json.loads(meta)
        except ValueError as exc:
            output_error(f"--meta is not valid JSON: {exc}")
            raise typer.Exit(1) from exc
        if not isinstance(parsed, dict):
            output_error("--meta must be a JSON object")
            raise typer.Exit(1)
        extra = parsed
    item = {"kind": kind, "snippet": text, "meta": extra}
    # Store-only hits the bare endpoint; deliver hits the batch send endpoint
    # that also emits the SSE deliver event (mirrors the store-vs-deliver split).
    path, payload = ("/selection", item) if no_deliver else ("/selection/send", {"items": [item]})
    try:
        data = _sidecar_post(path, payload)
    except httpx.HTTPError as exc:
        output_error(f"sidecar unreachable or rejected the send: {exc}")
        raise typer.Exit(1) from exc
    # /selection returns the record; /selection/send returns {records, count}.
    rec = (data.get("records") or [data])[0] if isinstance(data, dict) else {}
    if out.is_compact:
        print(
            f"selection-send:kind={rec.get('kind', kind)} "
            f"delivered={str(not no_deliver).lower()} "
            f'snippet="{_clip(rec.get("snippet", text), 80)}"'
        )
    else:
        output_json(data)
