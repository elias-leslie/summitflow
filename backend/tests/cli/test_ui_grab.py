"""Tests for `st ui grab` (capture package) and `st ui crop` (ROI).

`grab` assembles a directory — native image + OCR text + meta.json + index.md —
ranked cheapest-first so an agent reads the token-light items before the image.
`crop` pulls a region out of a saved image at full resolution. Both wrap the
host tools (import/tesseract/identify/convert), so the subprocess layer is
mocked the way `test_ui_ocr.py` does it, while the package files are written for
real into a tmp dir and asserted on.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import ui as ui_mod
from cli.commands.ui import app as ui_app

runner = CliRunner()


def _proc(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _make_side_effect(ocr_text: str = "US stocks 96%\nSuccess odds 52%"):
    """`import`/`convert` create their output file; `tesseract` returns OCR text."""

    def _side_effect(cmd, **_):
        if not cmd:
            return _proc()
        if cmd[0] in ("import", "convert"):
            Path(cmd[-1]).write_bytes(b"\x89PNG\r\n fake image bytes")
            return _proc()
        if cmd[0] == "tesseract":
            return _proc(stdout=ocr_text + "\n")
        return _proc()

    return _side_effect


def _patch_ui(dims=(3630, 3440)):
    """Common patches: real files, faked tool presence + image dimensions."""
    return (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod.shutil, "which", lambda b: f"/usr/bin/{b}"),
        patch.object(ui_mod, "_resolve_window", return_value=0x123),
        patch.object(ui_mod, "_window_title", return_value="Portfolio AI Platform"),
        patch.object(ui_mod, "_identify_dims", return_value=dims),
        patch.object(ui_mod, "_run", side_effect=_make_side_effect()),
    )


def test_grab_writes_full_package(tmp_path):
    out = tmp_path / "cap"
    p_req, p_which, p_resolve, p_title, p_dims, p_run = _patch_ui()
    with p_req, p_which, p_resolve, p_title, p_dims, p_run:
        result = runner.invoke(ui_app, ["grab", "-w", "Portfolio", "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert {"image.png", "text.txt", "meta.json", "index.md"} <= {p.name for p in out.iterdir()}
    # OCR text carries the number a downscaled screenshot would blur away.
    assert "96%" in (out / "text.txt").read_text()
    assert "grab:index=" in result.output and "items=3" in result.output


def test_grab_meta_records_dimensions_and_downscale(tmp_path):
    out = tmp_path / "cap"
    p_req, p_which, p_resolve, p_title, p_dims, p_run = _patch_ui()
    with p_req, p_which, p_resolve, p_title, p_dims, p_run:
        runner.invoke(ui_app, ["grab", "-w", "Portfolio", "-o", str(out)])

    meta = json.loads((out / "meta.json").read_text())
    assert meta["width"] == 3630 and meta["height"] == 3440
    # 3630px long edge > 1568px vision cap → flagged as downscaled.
    assert meta["downscaled_for_vision"] is True
    assert meta["has_text"] is True


def test_grab_index_ranks_cheapest_first_and_warns_on_downscale(tmp_path):
    out = tmp_path / "cap"
    p_req, p_which, p_resolve, p_title, p_dims, p_run = _patch_ui()
    with p_req, p_which, p_resolve, p_title, p_dims, p_run:
        runner.invoke(ui_app, ["grab", "-w", "Portfolio", "-o", str(out)])

    index = (out / "index.md").read_text()
    # The image (most expensive) must come after the text/meta rows in the table.
    assert index.index("meta.json") < index.index("image.png")
    assert index.index("text.txt") < index.index("image.png")
    # A downscaled capture points the agent at the crop escape hatch.
    assert "st ui crop" in index
    assert "DOWNSCALED" in index


def test_grab_no_downscale_for_small_capture(tmp_path):
    out = tmp_path / "cap"
    p_req, p_which, p_resolve, p_title, _, p_run = _patch_ui()
    with (
        p_req,
        p_which,
        p_resolve,
        p_title,
        patch.object(ui_mod, "_identify_dims", return_value=(800, 600)),
        p_run,
    ):
        result = runner.invoke(ui_app, ["grab", "-w", "Portfolio", "-o", str(out)])

    assert "downscaled=false" in result.output
    assert "st ui crop" not in (out / "index.md").read_text()


def test_grab_no_ocr_skips_text(tmp_path):
    out = tmp_path / "cap"
    p_req, p_which, p_resolve, p_title, p_dims, p_run = _patch_ui()
    with p_req, p_which, p_resolve, p_title, p_dims, p_run:
        result = runner.invoke(ui_app, ["grab", "-w", "Portfolio", "-o", str(out), "--no-ocr"])

    assert not (out / "text.txt").exists()
    assert "items=2" in result.output
    assert json.loads((out / "meta.json").read_text())["has_text"] is False


def test_crop_produces_region_file(tmp_path):
    src = tmp_path / "image.png"
    src.write_bytes(b"\x89PNG fake")
    dest = tmp_path / "roi.png"
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_identify_dims", return_value=(900, 520)),
        patch.object(ui_mod, "_run", side_effect=_make_side_effect()),
    ):
        result = runner.invoke(ui_app, ["crop", str(src), "900x520+170+2580", "-o", str(dest)])

    assert result.exit_code == 0, result.output
    assert dest.exists()
    assert "crop:path=" in result.output and "w=900" in result.output


def test_crop_rejects_missing_source(tmp_path):
    with patch.object(ui_mod, "_require", lambda b: b):
        result = runner.invoke(ui_app, ["crop", str(tmp_path / "nope.png"), "10x10+0+0"])
    assert result.exit_code == 1
    assert "not a file" in result.output


def test_est_image_tokens_clamps_long_edge():
    # Under the cap: linear in pixels, no downscale.
    tokens, down = ui_mod._est_image_tokens(750, 750)
    assert down is False and tokens == 750
    # Over the cap: long edge clamped to 1568 before the px/750 charge.
    tokens, down = ui_mod._est_image_tokens(3630, 3440)
    assert down is True
    assert tokens == round(1568 * round(3440 * (1568 / 3630)) / 750)
