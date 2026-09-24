"""The host cleanup caller must only dispatch to the registered owner capability."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REAPER = Path(__file__).resolve().parents[3] / "scripts" / "agent-browser-idle-reaper.js"


def test_cleanup_wrapper_dispatches_owner_from_nonproject_cwd(tmp_path):
    recorded = tmp_path / "arguments.json"
    stub = tmp_path / "st"
    stub.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
        + f"Path({str(recorded)!r}).write_text(json.dumps(sys.argv[1:]))\n"
    )
    stub.chmod(0o700)
    script = f"const r=require({json.dumps(str(REAPER))});process.exitCode=r.runIsolatedCleanup({{st:{json.dumps(str(stub))},dryRun:true}});"
    result = subprocess.run(["node", "-e", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(recorded.read_text()) == ["browser", "--local-ai", "reap-isolated", "--dry-run"]


def test_cleanup_wrapper_never_falls_back_to_global_reaper(tmp_path):
    script = f"const r=require({json.dumps(str(REAPER))});process.exitCode=r.runIsolatedCleanup({{st:{json.dumps(str(tmp_path / 'missing'))}}});"
    result = subprocess.run(["node", "-e", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "owner unavailable" in result.stderr


def test_legacy_wrapper_runs_only_requested_command_without_cleanup(tmp_path):
    import os

    root = Path(__file__).resolve().parents[3]
    stub = tmp_path / "agent-browser"
    stub.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
    stub.chmod(0o700)
    reaper = tmp_path / "unexpected-reaper"
    marker = tmp_path / "reaper-ran"
    reaper.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 99\n")
    reaper.chmod(0o700)
    env = {
        **os.environ,
        "AGENT_BROWSER_REAL_BIN": str(stub),
        "AGENT_BROWSER_REAPER_BIN": str(reaper),
        "AGENT_BROWSER_SOCKET_DIR": str(tmp_path / "sockets"),
        "AGENT_BROWSER_SKIP_NO_SANDBOX": "1",
    }
    result = subprocess.run(
        ["node", str(root / "scripts/agent-browser-wrapper.js"), "--session", "fixture", "snapshot"],
        env=env, cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == ["--session", "fixture", "snapshot"]
    assert not marker.exists()
