from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _read_log(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fake_curl_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
request="${*: -1}"
case "$request" in
  *"/json/version")
    printf '%s\n' '{"Browser":"Chrome/146.0.0.0","webSocketDebuggerUrl":"ws://0.0.0.0:9222/devtools/browser/test"}'
    ;;
  *"/json/list")
    printf '%s\n' '[]'
    ;;
  *"/json/close/"*)
    exit 0
    ;;
  *)
    printf '%s\n' '{}'
    ;;
esac
"""


def _fake_agent_browser_script() -> str:
    return """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

log_path = Path(os.environ["FAKE_AGENT_BROWSER_LOG"])
args = sys.argv[1:]
with log_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")

if "eval" in args:
    script = args[args.index("eval") + 1]
    submit_mode = os.environ.get("FAKE_SUBMIT_MODE", "submit")
    if "submitCapable" in script:
        if submit_mode == "submit":
            print('{"found":true,"disabled":false,"submitCapable":true}')
        elif submit_mode == "non-submit":
            print('{"found":true,"disabled":false,"submitCapable":false}')
        else:
            print('{"found":false}')
    elif "requestSubmit" in script:
        print('"submitted"')
    else:
        print("null")
elif "wait" in args:
    print("waited")
"""


def _run_sf_browser(tmp_path: Path, *, selector: str, submit_mode: str, extra_args: list[str] | None = None) -> list[list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_agent_browser = bin_dir / "agent-browser"
    fake_curl = bin_dir / "curl"
    log_path = tmp_path / "agent-browser-log.jsonl"

    _write_executable(fake_agent_browser, _fake_agent_browser_script())
    _write_executable(fake_curl, _fake_curl_script())

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AGENT_BROWSER_BIN": str(fake_agent_browser),
        "FAKE_AGENT_BROWSER_LOG": str(log_path),
        "FAKE_SUBMIT_MODE": submit_mode,
        "SF_BROWSER_HOST": "192.0.2.10",
    }

    command = [str(script_path), *(extra_args or []), "click", selector]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    return _read_log(log_path)


def test_sf_browser_submit_button_uses_request_submit(tmp_path: Path) -> None:
    calls = _run_sf_browser(tmp_path, selector="#finance-entry-composer button[type='submit']", submit_mode="submit")

    assert any("eval" in call and "submitCapable" in call[call.index("eval") + 1] for call in calls)
    assert any("eval" in call and "requestSubmit" in call[call.index("eval") + 1] for call in calls)
    assert not any("click" in call for call in calls)


def test_sf_browser_non_submit_selector_uses_click(tmp_path: Path) -> None:
    calls = _run_sf_browser(tmp_path, selector="#plain-button", submit_mode="non-submit")

    assert any("eval" in call and "submitCapable" in call[call.index("eval") + 1] for call in calls)
    assert any("click" in call for call in calls)
    assert not any("eval" in call and "requestSubmit" in call[call.index("eval") + 1] for call in calls)


def test_sf_browser_snapshot_ref_bypasses_submit_probe(tmp_path: Path) -> None:
    calls = _run_sf_browser(tmp_path, selector="@e18", submit_mode="submit")

    assert any("click" in call for call in calls)
    assert not any("eval" in call and "submitCapable" in call[call.index("eval") + 1] for call in calls)


def test_sf_browser_sessioned_click_still_uses_request_submit(tmp_path: Path) -> None:
    calls = _run_sf_browser(
        tmp_path,
        selector="#finance-entry-composer button[type='submit']",
        submit_mode="submit",
        extra_args=["--session", "verification"],
    )

    assert any("eval" in call and "requestSubmit" in call[call.index("eval") + 1] for call in calls)
    assert not any("click" in call for call in calls)
