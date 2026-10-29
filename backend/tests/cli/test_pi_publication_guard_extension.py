"""Exercise the real Pi publication guard extension against the real and a failing hook."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
EXTENSION = ROOT / "scripts/lib/pi-publication-guard-extension.ts"


def _run(tmp_path: Path, tool: str, command: str, *, scripts: Path | None, extension: Path = EXTENSION) -> Any:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the Pi extension fixture")
    script = tmp_path / "fixture.mjs"
    script.write_text(
        f"import adapter from '{extension.as_uri()}';\n"
        "let handler; adapter({on: (name, fn) => { handler = fn; }});\n"
        f"const event = {{toolName: {json.dumps(tool)}, toolCallId: 'c1', input: {{command: {json.dumps(command)}}}}};\n"
        "console.log(JSON.stringify((await handler(event, {cwd: process.cwd()})) ?? null));\n"
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    if scripts is not None:
        env["SUMMITFLOW_SCRIPTS_DIR"] = str(scripts)
    result = subprocess.run([node, str(script)], env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_publication_is_blocked_with_the_guards_reason_and_other_calls_pass(tmp_path) -> None:
    blocked = _run(tmp_path, "bash", "git push origin main", scripts=ROOT / "scripts")
    assert blocked == {"block": True, "reason": "Use the canonical ST publication workflow."}
    assert _run(tmp_path, "bash", "ls -la", scripts=ROOT / "scripts") is None
    assert _run(tmp_path, "read", "git push", scripts=ROOT / "scripts") is None


def test_a_guard_that_errors_blocks_and_a_missing_guard_does_not_apply(tmp_path) -> None:
    broken = tmp_path / "broken"
    (broken / "lib").mkdir(parents=True)
    (broken / "lib/publication-pretool-hook").write_text("#!/usr/bin/env bash\nexit 3\n")
    result = _run(tmp_path, "bash", "ls", scripts=broken)
    assert result["block"] is True and "refused" in result["reason"]

    alone = tmp_path / "alone"
    alone.mkdir()
    copied = alone / EXTENSION.name
    copied.write_text(EXTENSION.read_text())
    assert _run(tmp_path, "bash", "git push", scripts=None, extension=copied) is None
