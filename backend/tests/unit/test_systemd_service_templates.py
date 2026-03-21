from __future__ import annotations

import re
from pathlib import Path

SYSTEMD_DIR = Path(__file__).resolve().parents[3] / "scripts" / "systemd"
APP_SERVICE_KILLMODES = {
    "summitflow-backend.service": "control-group",
    "summitflow-frontend.service": "mixed",
    "summitflow-hatchet-worker.service": "control-group",
    "summitflow-terminal.service": "mixed",
    "summitflow-terminal-frontend.service": "mixed",
}
SUMMITFLOW_ROOT_RENDERED_UNITS = [
    "summitflow-backend.service",
    "summitflow-frontend.service",
    "summitflow-hatchet-worker.service",
    "codex-session-sync.service",
    "tmux-agent-session-sync.service",
    "agent-browser-idle-reaper.service",
]
TERMINAL_ROOT_RENDERED_UNITS = [
    "summitflow-terminal.service",
    "summitflow-terminal-frontend.service",
]


def _kill_mode_for(service_name: str) -> str | None:
    text = (SYSTEMD_DIR / service_name).read_text()
    match = re.search(r"^KillMode=(.+)$", text, re.MULTILINE)
    return match.group(1) if match else None


def test_app_service_templates_use_expected_kill_mode() -> None:
    for service_name, expected_mode in APP_SERVICE_KILLMODES.items():
        assert _kill_mode_for(service_name) == expected_mode


def test_app_service_templates_do_not_use_process_kill_mode() -> None:
    for service_name in APP_SERVICE_KILLMODES:
        assert _kill_mode_for(service_name) != "process"


def test_summitflow_units_use_root_placeholder_instead_of_hardcoded_home_path() -> None:
    for service_name in SUMMITFLOW_ROOT_RENDERED_UNITS:
        text = (SYSTEMD_DIR / service_name).read_text()
        assert "__SUMMITFLOW_ROOT__" in text
        assert "%h/summitflow" not in text


def test_terminal_units_use_terminal_root_placeholder_instead_of_hardcoded_home_path() -> None:
    for service_name in TERMINAL_ROOT_RENDERED_UNITS:
        text = (SYSTEMD_DIR / service_name).read_text()
        assert "__TERMINAL_ROOT__" in text
        assert "%h/terminal" not in text
