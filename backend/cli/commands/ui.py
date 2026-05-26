"""Desktop UI control surface: screenshot, OCR, window management, and input.

Wraps the host control tools (import/scrot, tesseract, wmctrl/xdotool, xclip,
ImageMagick compare) behind a single `st ui` family with TOON-compact output.
Keyboard input goes through ydotool (kernel /dev/uinput) because X11 synthetic
keyboard events do not reach apps in this GNOME-on-Xorg session; the pointer,
window, and capture ops use X11 directly (Wayland not supported — see the aico
phase0-wayland-spike notes). Input/window subcommands are mutating; windows,
shot, ocr, diff, and clip get are read-only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Annotated

import typer

from ..output import output_error, output_json, output_success
from ..output_context import OutputContext

app = typer.Typer(help="Desktop UI control: screenshot, OCR, window management, input (X11).")

_SHOT_DIR = Path("/tmp")


def _ctx(ctx: typer.Context) -> OutputContext:
    if ctx.obj is None:
        ctx.obj = OutputContext()
    return ctx.obj


def _fail(message: str) -> None:
    output_error(message)
    raise typer.Exit(1)


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        _fail(f"{binary} not installed (apt install it on the host)")
    return path  # type: ignore[return-value]


def _x_env() -> dict[str, str]:
    """Environment for X11 subprocesses.

    The agent shell often has empty DISPLAY/XAUTHORITY; resolve sensible
    defaults for the live GNOME-on-Xorg session. Override via ST_UI_DISPLAY /
    ST_UI_XAUTHORITY.
    """
    env = dict(os.environ)
    display = os.environ.get("ST_UI_DISPLAY") or os.environ.get("DISPLAY") or ":0"
    env["DISPLAY"] = display
    xauth = os.environ.get("ST_UI_XAUTHORITY") or os.environ.get("XAUTHORITY") or ""
    if not xauth or not Path(xauth).exists():
        uid = os.getuid()
        candidates = [
            f"/run/user/{uid}/gdm/Xauthority",
            str(Path.home() / ".Xauthority"),
        ]
        xauth = next((c for c in candidates if Path(c).exists()), xauth)
    if xauth:
        env["XAUTHORITY"] = xauth
    return env


def _run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, env=_x_env(), capture_output=capture, text=True, check=False)


def _ydotool(args: list[str], *, stdin: str | None = None) -> None:
    """Run ydotool for keyboard injection (kernel /dev/uinput).

    X11 synthetic keyboard events (XTEST/XSendEvent) do not reach apps in this
    GNOME-on-Xorg session, so keyboard goes through uinput instead. Type into
    whatever currently has input focus — activate the target window first.
    """
    _require("ydotool")
    if not os.access("/dev/uinput", os.W_OK):
        _fail("/dev/uinput not writable; keyboard injection unavailable (see /etc/udev/rules.d/99-uinput.rules)")
    proc = subprocess.run(
        ["ydotool", *args], env=_x_env(), input=stdin, text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        _fail(f"ydotool failed: {proc.stderr.strip()}")


def _resolve_window(target: str) -> int:
    """Resolve a window id (decimal/hex) or name substring to a decimal id."""
    t = target.strip()
    if t.lower().startswith("0x"):
        return int(t, 16)
    if t.isdigit():
        return int(t)
    _require("xdotool")
    res = _run(["xdotool", "search", "--name", t])
    ids = [line for line in res.stdout.split() if line.strip()]
    if not ids:
        _fail(f"no window matches name {target!r}")
    return int(ids[-1])


def _focused_window() -> str:
    """Active window id as a string, or 'root' if it can't be determined.

    The same resolution `st ui shot` uses for its default (focused) target.
    """
    act = _run(["xdotool", "getactivewindow"]) if shutil.which("xdotool") else None
    return act.stdout.strip() if act and act.returncode == 0 and act.stdout.strip() else "root"


def _identify_dims(path: str) -> tuple[int, int]:
    _require("identify")
    res = _run(["identify", "-format", "%w %h", path])
    if res.returncode != 0:
        _fail(f"identify failed: {res.stderr.strip()}")
    w, h = res.stdout.split()[:2]
    return int(w), int(h)


# Claude clamps an image's long edge before charging tokens; a capture taller/
# wider than this is downscaled, which is exactly what makes small text (the
# "96%→50%" misread) illegible. We mirror the clamp so the package index can warn.
_VISION_LONG_EDGE = 1568  # conservative across models (Opus 4.7 allows 2576)


def _est_image_tokens(w: int, h: int) -> tuple[int, bool]:
    """Estimate the tokens an image costs Claude, and whether it gets downscaled.

    Claude bills ~`pixels / 750` after clamping the long edge to ~1568px. Returns
    `(tokens, downscaled)` so the index can flag captures whose text will blur.
    """
    long_edge = max(w, h)
    downscaled = long_edge > _VISION_LONG_EDGE
    if downscaled:
        scale = _VISION_LONG_EDGE / long_edge
        w, h = round(w * scale), round(h * scale)
    return max(1, round(w * h / 750)), downscaled


def _est_text_tokens(text: str) -> int:
    """Rough token estimate for text (~4 chars/token)."""
    return max(1, round(len(text) / 4))


def _window_title(wid: str) -> str:
    """Best-effort window title for a numeric/hex window id ('' if unknown)."""
    if not shutil.which("xdotool"):
        return ""
    res = _run(["xdotool", "getwindowname", wid])
    return res.stdout.strip() if res.returncode == 0 else ""


def _human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


@app.command()
def windows(ctx: typer.Context) -> None:
    """List visible windows: id, name, geometry, focused.

    Examples: st ui windows | st ui windows --human
    """
    out = _ctx(ctx)
    _require("wmctrl")
    res = _run(["wmctrl", "-lG"])
    if res.returncode != 0:
        _fail(f"wmctrl failed: {res.stderr.strip()}")
    active = 0
    act = _run(["xdotool", "getactivewindow"]) if shutil.which("xdotool") else None
    if act and act.returncode == 0 and act.stdout.strip().isdigit():
        active = int(act.stdout.strip())
    rows = []
    for line in res.stdout.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        wid_hex, _desktop, x, y, w, h, _host, title = parts
        wid = int(wid_hex, 16)
        rows.append(
            {
                "id": wid,
                "name": title,
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "focused": wid == active,
            }
        )
    if out.is_compact:
        print(f"windows[{len(rows)}]{{id,name,x,y,w,h,focused}}:")
        for r in rows:
            print(f"  {r['id']},{r['name']},{r['x']},{r['y']},{r['w']},{r['h']},{str(r['focused']).lower()}")
    else:
        output_json(rows)


@app.command()
def shot(
    ctx: typer.Context,
    window: Annotated[str | None, typer.Option("--window", "-w", help="Window id or name substring")] = None,
    full: Annotated[bool, typer.Option("--full", help="Capture the whole screen")] = False,
    region: Annotated[str | None, typer.Option("--region", help="Crop region WxH+X+Y")] = None,
    out_path: Annotated[str | None, typer.Option("--out", "-o", help="Output PNG path")] = None,
) -> None:
    """Capture a screenshot. Default target is the focused window.

    Examples: st ui shot | st ui shot -w aico -o /tmp/aico.png | st ui shot --full
    """
    octx = _ctx(ctx)
    _require("import")
    dest = out_path or str(_SHOT_DIR / f"st-ui-shot-{int(time.time())}.png")
    if full:
        wid = "root"
    elif window:
        wid = str(_resolve_window(window))
    else:
        wid = _focused_window()
    cmd = ["import", "-window", wid]
    if region:
        cmd += ["-crop", region, "+repage"]
    cmd.append(dest)
    res = _run(cmd)
    if res.returncode != 0:
        _fail(f"capture failed: {res.stderr.strip()}")
    w, h = _identify_dims(dest)
    if octx.is_compact:
        print(f"shot:path={dest}|w={w}|h={h}")
    else:
        output_json({"path": dest, "w": w, "h": h})


def _write_index(
    pkg: Path, source: str, items: list[dict[str, object]], hint: str
) -> Path:
    """Write the package manifest: items cheapest-first with size + token cost.

    An agent reads this first, then the cheap text/meta, and only opens the image
    when pixels are actually needed. Items arrive pre-sorted by estimated tokens.
    """
    lines = [
        f"# Aico capture — {source}",
        "",
        "Read items cheapest-first. The text + metadata usually answer the question;",
        "open the image only when you need pixel detail (layout, charts, an icon).",
        "The text is OCR — it may scramble columns or garble exact figures (money,",
        "small digits), so crop the image to confirm any precise value it implies.",
        "",
        "| item | kind | what it is | size | ~tokens |",
        "| --- | --- | --- | --- | --- |",
    ]
    for it in items:
        lines.append(
            f"| `{it['file']}` | {it['kind']} | {it['desc']} | {it['size']} | {it['tokens']} |"
        )
    if hint:
        lines += ["", hint]
    lines.append("")
    index = pkg / "index.md"
    index.write_text("\n".join(lines), encoding="utf-8")
    return index


@app.command()
def grab(
    ctx: typer.Context,
    window: Annotated[str | None, typer.Option("--window", "-w", help="Window id or name substring")] = None,
    full: Annotated[bool, typer.Option("--full", help="Capture the whole screen")] = False,
    region: Annotated[str | None, typer.Option("--region", help="Crop region WxH+X+Y")] = None,
    out_dir: Annotated[str | None, typer.Option("--out", "-o", help="Output package directory")] = None,
    ocr: Annotated[bool, typer.Option("--ocr/--no-ocr", help="Include an OCR text representation")] = True,
) -> None:
    """Capture a screenshot *package*: native image + OCR text + metadata + an
    index that ranks each item by token cost (cheapest first).

    Solves the "agent misreads a downscaled screenshot" problem: the native image
    is preserved for `st ui crop`, but the cheap text/meta come first so the agent
    rarely needs to spend tokens (or risk a blurry read) on the full image.

    Examples: st ui grab -w aico | st ui grab --region 800x600+100+100 -o /tmp/cap
    """
    octx = _ctx(ctx)
    _require("import")
    pkg = Path(out_dir) if out_dir else _SHOT_DIR / f"st-ui-grab-{int(time.time())}"
    pkg.mkdir(parents=True, exist_ok=True)

    if full:
        wid, source = "root", "full screen"
    elif window:
        wid = str(_resolve_window(window))
        source = f'window "{_window_title(wid) or window}"'
    else:
        wid = _focused_window()
        source = f'focused window "{_window_title(wid)}"'.replace(' ""', "")
    if region:
        source += f" (region {region})"

    image = pkg / "image.png"
    cmd = ["import", "-window", wid]
    if region:
        cmd += ["-crop", region, "+repage"]
    cmd.append(str(image))
    res = _run(cmd)
    if res.returncode != 0:
        _fail(f"capture failed: {res.stderr.strip()}")
    w, h = _identify_dims(str(image))
    img_tokens, downscaled = _est_image_tokens(w, h)

    items: list[dict[str, object]] = []

    text = ""
    if ocr and shutil.which("tesseract"):
        ocr_res = _run(["tesseract", str(image), "stdout"])
        if ocr_res.returncode == 0:
            text = ocr_res.stdout.strip()
            text_path = pkg / "text.txt"
            text_path.write_text(text, encoding="utf-8")
            items.append(
                {
                    "file": "text.txt",
                    "kind": "text",
                    "desc": "OCR transcription of all readable text",
                    "size": _human_bytes(len(text.encode())),
                    "tokens": f"~{_est_text_tokens(text)}",
                    "_t": _est_text_tokens(text),
                }
            )

    captured_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta = {
        "captured_at": captured_at,
        "source": source,
        "window": wid,
        "region": region,
        "image": "image.png",
        "width": w,
        "height": h,
        "downscaled_for_vision": downscaled,
        "has_text": bool(text),
    }
    meta_path = pkg / "meta.json"
    meta_blob = json.dumps(meta, indent=2)
    meta_path.write_text(meta_blob, encoding="utf-8")
    items.append(
        {
            "file": "meta.json",
            "kind": "json",
            "desc": "source window, geometry, dimensions, capture time",
            "size": _human_bytes(len(meta_blob.encode())),
            "tokens": f"~{_est_text_tokens(meta_blob)}",
            "_t": _est_text_tokens(meta_blob),
        }
    )

    img_note = f"native screenshot {w}x{h}"
    if downscaled:
        img_note += (
            " — DOWNSCALED for vision; small/body text may blur (large headline"
            " numbers usually survive), crop for detail"
        )
    items.append(
        {
            "file": "image.png",
            "kind": "image",
            "desc": img_note,
            "size": _human_bytes(image.stat().st_size),
            "tokens": f"~{img_tokens}",
            "_t": img_tokens,
        }
    )

    items.sort(key=lambda it: it["_t"])  # cheapest first
    hint = ""
    if downscaled:
        hint = (
            "The image is larger than the vision long-edge limit, so reading it whole "
            "loses small-text detail. To read a region at full resolution:\n"
            f"  `st ui crop {image} <WxH+X+Y> -o /tmp/roi.png`"
        )
    for it in items:
        it.pop("_t", None)
    index = _write_index(pkg, source, items, hint)

    if octx.is_compact:
        print(f"grab:index={index}|items={len(items)}|w={w}|h={h}|downscaled={str(downscaled).lower()}")
    else:
        output_json(
            {
                "index": str(index),
                "dir": str(pkg),
                "items": len(items),
                "w": w,
                "h": h,
                "downscaled": downscaled,
                "image_tokens": img_tokens,
            }
        )


@app.command()
def crop(
    ctx: typer.Context,
    image: Annotated[str, typer.Argument(help="Source image path")],
    region: Annotated[str, typer.Argument(help="Crop region WxH+X+Y (pixels in the source image)")],
    out_path: Annotated[str | None, typer.Option("--out", "-o", help="Output PNG path")] = None,
) -> None:
    """Crop a region out of a saved image at full resolution.

    The companion to `st ui grab`: when the package image is downscaled for vision,
    crop the region of interest from the native file so its text reads cleanly.

    Examples: st ui crop /tmp/cap/image.png 600x300+1200+800 -o /tmp/roi.png
    """
    octx = _ctx(ctx)
    _require("convert")
    if not Path(image).is_file():
        _fail(f"not a file: {image}")
    dest = out_path or str(_SHOT_DIR / f"st-ui-crop-{int(time.time())}.png")
    res = _run(["convert", image, "-crop", region, "+repage", dest])
    if res.returncode != 0:
        _fail(f"crop failed: {res.stderr.strip()}")
    w, h = _identify_dims(dest)
    if octx.is_compact:
        print(f"crop:path={dest}|w={w}|h={h}")
    else:
        output_json({"path": dest, "w": w, "h": h})


@app.command()
def ocr(
    ctx: typer.Context,
    target: Annotated[
        str | None,
        typer.Argument(help="Window id/name or image path; default = focused window"),
    ] = None,
) -> None:
    """Read text from a window or image via OCR. Default target is the focused window.

    Examples: st ui ocr | st ui ocr aico | st ui ocr /tmp/shot.png
    """
    octx = _ctx(ctx)
    _require("tesseract")
    if target is not None and Path(target).is_file():
        img = target
    else:
        _require("import")
        wid = _focused_window() if target is None else str(_resolve_window(target))
        img = str(_SHOT_DIR / f"st-ui-ocr-{int(time.time())}.png")
        cap = _run(["import", "-window", wid, img])
        if cap.returncode != 0:
            _fail(f"capture failed: {cap.stderr.strip()}")
    res = _run(["tesseract", img, "stdout"])
    if res.returncode != 0:
        _fail(f"tesseract failed: {res.stderr.strip()}")
    text = res.stdout.strip()
    if octx.is_compact:
        print(text)
    else:
        output_json({"text": text})


@app.command()
def diff(
    ctx: typer.Context,
    a: Annotated[str, typer.Argument(help="First image")],
    b: Annotated[str, typer.Argument(help="Second image")],
    out_path: Annotated[str | None, typer.Option("--out", "-o", help="Diff image path")] = None,
) -> None:
    """Compare two images; report differing-pixel count and percentage.

    Examples: st ui diff a.png b.png | st ui diff a.png b.png -o /tmp/diff.png
    """
    octx = _ctx(ctx)
    _require("compare")
    for p in (a, b):
        if not Path(p).is_file():
            _fail(f"not a file: {p}")
    dest = out_path or str(_SHOT_DIR / f"st-ui-diff-{int(time.time())}.png")
    res = _run(["compare", "-metric", "AE", a, b, dest])
    # compare prints the AE count to stderr; rc 0=identical, 1=different, 2=error
    if res.returncode == 2:
        _fail(f"compare failed: {res.stderr.strip()}")
    token = res.stderr.strip().split()[0] if res.stderr.strip() else "0"
    try:
        ae = float(token)
    except ValueError:
        ae = 0.0
    w, h = _identify_dims(a)
    total = max(w * h, 1)
    pct = round(ae / total * 100, 4)
    if octx.is_compact:
        print(f"diff:pixels={int(ae)}|pct={pct}|out={dest}")
    else:
        output_json({"pixels": int(ae), "pct": pct, "out": dest})


@app.command()
def activate(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Window id or name substring")],
) -> None:
    """Focus/raise a window. Example: st ui activate aico"""
    _require("xdotool")
    wid = _resolve_window(target)
    # windowactivate raises via the WM; windowfocus sets X input focus directly
    # (mutter's focus-stealing prevention can otherwise raise without focusing).
    res = _run(["xdotool", "windowactivate", "--sync", str(wid)])
    _run(["xdotool", "windowfocus", "--sync", str(wid)])
    if res.returncode != 0:
        _fail(f"activate failed: {res.stderr.strip()}")
    output_success(f"activated {wid}")


@app.command()
def move(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Window id or name substring")],
    x: Annotated[int, typer.Argument(help="X position")],
    y: Annotated[int, typer.Argument(help="Y position")],
) -> None:
    """Move a window. Example: st ui move aico 100 100"""
    _require("xdotool")
    wid = _resolve_window(target)
    res = _run(["xdotool", "windowmove", str(wid), str(x), str(y)])
    if res.returncode != 0:
        _fail(f"move failed: {res.stderr.strip()}")
    output_success(f"moved {wid} to {x},{y}")


@app.command()
def resize(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Window id or name substring")],
    w: Annotated[int, typer.Argument(help="Width")],
    h: Annotated[int, typer.Argument(help="Height")],
) -> None:
    """Resize a window. Example: st ui resize aico 1200 800"""
    _require("xdotool")
    wid = _resolve_window(target)
    res = _run(["xdotool", "windowsize", str(wid), str(w), str(h)])
    if res.returncode != 0:
        _fail(f"resize failed: {res.stderr.strip()}")
    output_success(f"resized {wid} to {w}x{h}")


@app.command()
def close(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Window id or name substring")],
) -> None:
    """Close a window (graceful). Example: st ui close aico"""
    _require("xdotool")
    wid = _resolve_window(target)
    res = _run(["xdotool", "windowclose", str(wid)])
    if res.returncode != 0:
        _fail(f"close failed: {res.stderr.strip()}")
    output_success(f"closed {wid}")


@app.command()
def click(
    ctx: typer.Context,
    x: Annotated[int, typer.Argument(help="X coordinate")],
    y: Annotated[int, typer.Argument(help="Y coordinate")],
    button: Annotated[int, typer.Option("--button", "-b", help="Mouse button (1=left,2=mid,3=right)")] = 1,
) -> None:
    """Move the pointer and click. Example: st ui click 1200 800"""
    _require("xdotool")
    res = _run(["xdotool", "mousemove", "--sync", str(x), str(y), "click", str(button)])
    if res.returncode != 0:
        _fail(f"click failed: {res.stderr.strip()}")
    output_success(f"clicked {x},{y} button={button}")


@app.command(name="type")
def type_text(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="Text to type")],
) -> None:
    """Type text into the focused window. Example: st ui type \"hello\"

    Goes to the focused window via uinput — run `st ui activate <win>` first.
    """
    # --file - reads the literal text from stdin, avoiding arg parsing of leading dashes.
    _ydotool(["type", "--file", "-"], stdin=text)
    output_success(f"typed {len(text)} chars")


@app.command()
def key(
    ctx: typer.Context,
    keys: Annotated[str, typer.Argument(help="Key/chord, e.g. ctrl+c or Return")],
) -> None:
    """Send a key or chord to the focused window. Example: st ui key ctrl+c

    Chord syntax: modifiers and keys joined by '+', e.g. ctrl+c, alt+F4, Return.
    Goes to the focused window via uinput — run `st ui activate <win>` first.
    """
    _ydotool(["key", keys])
    output_success(f"sent {keys}")


@app.command()
def clip(
    ctx: typer.Context,
    action: Annotated[str, typer.Argument(help="get | set")],
    text: Annotated[str | None, typer.Argument(help="Text to set (for 'set')")] = None,
) -> None:
    """Read or write the clipboard. Examples: st ui clip get | st ui clip set \"hi\""""
    octx = _ctx(ctx)
    _require("xclip")
    if action == "get":
        res = _run(["xclip", "-selection", "clipboard", "-o"])
        if res.returncode != 0:
            _fail(f"clip get failed: {res.stderr.strip()}")
        if octx.is_compact:
            print(res.stdout)
        else:
            output_json({"text": res.stdout})
    elif action == "set":
        if text is None:
            _fail("clip set requires text")
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-i"],
            env=_x_env(),
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            _fail(f"clip set failed: {proc.stderr.strip()}")
        output_success(f"clipboard set ({len(text or '')} chars)")
    else:
        _fail("action must be 'get' or 'set'")
