from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _read_log(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fake_curl_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
request="${*: -1}"
if [[ -n "${FAKE_CURL_LOG:-}" ]]; then
  printf '%s\\n' "$request" >> "${FAKE_CURL_LOG}"
fi
case "$request" in
  *"/json/new?"*)
    printf '%s\n' '{"id":"TESTTAB","webSocketDebuggerUrl":"ws://0.0.0.0:9222/devtools/page/TESTTAB"}'
    ;;
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

if "--version" in args:
    print(os.environ.get("FAKE_AGENT_BROWSER_VERSION", "agent-browser 0.21.4"))
elif "eval" in args:
    script = args[args.index("eval") + 1]
    submit_mode = os.environ.get("FAKE_SUBMIT_MODE", "submit")
    if "window.__sfErrors = []" in script and os.environ.get("FAKE_CAPTURE_FAIL") == "1":
        sys.exit(1)
    elif "submitCapable" in script:
        if submit_mode == "submit":
            print('{"found":true,"disabled":false,"submitCapable":true}')
        elif submit_mode == "non-submit":
            print('{"found":true,"disabled":false,"submitCapable":false}')
        else:
            print('{"found":false}')
    elif "requestSubmit" in script:
        print('"submitted"')
    elif "window.__sfErrors" in script and "title: document.title" in script:
        print('{"errors":[],"warnings":[],"url":"http://example.test/","title":"Example"}')
    elif "performance.getEntriesByType('resource')" in script:
        print("[]")
    else:
        print("null")
elif "wait" in args:
    wait_seconds = float(os.environ.get("FAKE_WAIT_SECONDS", "0"))
    if wait_seconds > 0:
        import time

        time.sleep(wait_seconds)
    print("waited")
"""


def _fake_npm_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "view" && "${2:-}" == "agent-browser" && "${3:-}" == "version" ]]; then
  printf '%s\\n' "${FAKE_AGENT_BROWSER_LATEST:-0.26.0}"
  exit 0
fi
exit 1
"""


def _fake_systemctl_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
mode="${2:-}"
case "${1:-}" in
  --user)
    shift
    mode="${1:-}"
    ;;
esac
case "$mode" in
  is-enabled)
    printf '%s\\n' "${FAKE_SYSTEMCTL_ENABLED:-enabled}"
    ;;
  is-active)
    printf '%s\\n' "${FAKE_SYSTEMCTL_ACTIVE:-active}"
    ;;
  *)
    exit 1
    ;;
esac
"""


def _prepare_sf_browser_env(
    tmp_path: Path,
    *,
    submit_mode: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_agent_browser = bin_dir / "agent-browser"
    fake_curl = bin_dir / "curl"
    fake_npm = bin_dir / "npm"
    fake_systemctl = bin_dir / "systemctl"
    agent_log_path = tmp_path / "agent-browser-log.jsonl"
    curl_log_path = tmp_path / "curl-log.txt"

    _write_executable(fake_agent_browser, _fake_agent_browser_script())
    _write_executable(fake_curl, _fake_curl_script())
    _write_executable(fake_npm, _fake_npm_script())
    _write_executable(fake_systemctl, _fake_systemctl_script())

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AGENT_BROWSER_BIN": str(fake_agent_browser),
        "FAKE_AGENT_BROWSER_LOG": str(agent_log_path),
        "FAKE_CURL_LOG": str(curl_log_path),
        "FAKE_SUBMIT_MODE": submit_mode,
        "SF_BROWSER_HOST": "192.0.2.10",
    }
    if extra_env:
        env.update(extra_env)
    return env, agent_log_path, curl_log_path


def _run_sf_browser(tmp_path: Path, *, selector: str, submit_mode: str, extra_args: list[str] | None = None) -> list[list[str]]:
    env, agent_log_path, _ = _prepare_sf_browser_env(tmp_path, submit_mode=submit_mode)
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"

    command = [str(script_path), *(extra_args or []), "click", selector]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    return _read_log(agent_log_path)


def _run_sf_browser_check(
    tmp_path: Path,
    *,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], list[str]]:
    env, agent_log_path, curl_log_path = _prepare_sf_browser_env(
        tmp_path,
        submit_mode="submit",
        extra_env=extra_env,
    )
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"
    screenshot_path = tmp_path / "check.png"
    command = [str(script_path), "check", *(extra_args or []), "http://example.test", str(screenshot_path)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    return result, _read_log(agent_log_path), _read_lines(curl_log_path)


def _run_sf_browser_open(
    tmp_path: Path,
    *,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    env, agent_log_path, _ = _prepare_sf_browser_env(
        tmp_path,
        submit_mode="submit",
        extra_env=extra_env,
    )
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"
    command = [str(script_path), *(extra_args or []), "open", "http://example.test"]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    return result, _read_log(agent_log_path)


def _run_sf_browser_update(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env, _, _ = _prepare_sf_browser_env(
        tmp_path,
        submit_mode="submit",
        extra_env=extra_env,
    )
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"
    result = subprocess.run(
        [str(script_path), "update"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    return result


def _session_names(calls: list[list[str]]) -> list[str]:
    sessions: list[str] = []
    for call in calls:
        if "--session" in call:
            sessions.append(call[call.index("--session") + 1])
    return sessions


def test_sf_browser_help_describes_wrapper(tmp_path: Path) -> None:
    env, agent_log_path, _ = _prepare_sf_browser_env(tmp_path, submit_mode="submit")
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"

    result = subprocess.run(
        [str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "sf-browser - SummitFlow browser automation wrapper" in result.stdout
    assert "Usage: agent-browser" not in result.stdout
    assert "sf-browser console --clear" in result.stdout
    assert "sf-browser close" in result.stdout
    assert "If localhost fails from the remote browser VM" in result.stdout
    assert _read_log(agent_log_path) == []


def test_sf_browser_update_reports_runtime_diagnostics(tmp_path: Path) -> None:
    result = _run_sf_browser_update(tmp_path)

    assert "agent-browser: installed=0.21.4 latest=0.26.0" in result.stdout
    assert "host: 192.0.2.10" in result.stdout
    assert "agent-browser-bin:" in result.stdout
    assert "idle-reaper-bin:" in result.stdout
    assert "idle-reaper-timer: enabled (active)" in result.stdout


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


def test_sf_browser_open_reapplies_default_viewport_after_navigation(tmp_path: Path) -> None:
    _, calls = _run_sf_browser_open(tmp_path)

    viewport_calls = [
        index
        for index, call in enumerate(calls)
        if len(call) >= 6 and call[-4:] == ["set", "viewport", "1600", "900"]
    ]
    open_call_index = next(index for index, call in enumerate(calls) if "open" in call)

    assert len(viewport_calls) == 2
    assert viewport_calls[0] < open_call_index < viewport_calls[1]


def test_sf_browser_check_uses_generated_session_and_closes_only_current_tab(tmp_path: Path) -> None:
    result, calls, curl_requests = _run_sf_browser_check(tmp_path)

    sessions = _session_names(calls)
    assert sessions
    assert len(set(sessions)) == 1
    assert sessions[0].startswith("sf-browser-check-")
    assert not any(call[-2:] == ["tab", "close"] for call in calls)
    assert any("/json/new?" in request for request in curl_requests)
    assert any("/json/list" in request for request in curl_requests)
    assert any("/json/close/TESTTAB" in request for request in curl_requests)
    assert "No console errors, warnings, or failed network requests." in result.stdout


def test_sf_browser_check_captures_desktop_narrow_and_mobile_by_default(tmp_path: Path) -> None:
    result, calls, _ = _run_sf_browser_check(tmp_path)

    screenshot_calls = [call for call in calls if "screenshot" in call]
    screenshot_paths = [call[-1] for call in screenshot_calls]

    assert screenshot_paths == [
        str(tmp_path / "check.png"),
        str(tmp_path / "check-narrow.png"),
        str(tmp_path / "check-mobile.png"),
    ]
    assert "Additional screenshots:" in result.stdout
    assert f"narrow: {tmp_path / 'check-narrow.png'}" in result.stdout
    assert f"mobile: {tmp_path / 'check-mobile.png'}" in result.stdout


def test_sf_browser_check_preserves_explicit_session(tmp_path: Path) -> None:
    _, calls, _ = _run_sf_browser_check(tmp_path, extra_args=["--session", "verification"])

    sessions = _session_names(calls)
    assert sessions
    assert set(sessions) == {"verification"}


def test_sf_browser_check_tolerates_console_hook_failures(tmp_path: Path) -> None:
    result, _, _ = _run_sf_browser_check(tmp_path, extra_env={"FAKE_CAPTURE_FAIL": "1"})

    assert "Screenshot:" in result.stdout
    assert "No console errors, warnings, or failed network requests." in result.stdout


def test_sf_browser_check_serializes_parallel_runs(tmp_path: Path) -> None:
    env, _, _ = _prepare_sf_browser_env(
        tmp_path,
        submit_mode="submit",
        extra_env={
            "FAKE_WAIT_SECONDS": "0.25",
            "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        },
    )
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "sf-browser"
    first = subprocess.Popen(
        [str(script_path), "check", "http://example.test/one", str(tmp_path / "one.png")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    second = subprocess.Popen(
        [str(script_path), "check", "http://example.test/two", str(tmp_path / "two.png")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    start = time.monotonic()
    first_stdout, first_stderr = first.communicate(timeout=15)
    second_stdout, second_stderr = second.communicate(timeout=15)
    elapsed = time.monotonic() - start

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr
    assert elapsed >= 2.5
    assert "Screenshot:" in first_stdout
    assert "Screenshot:" in second_stdout
