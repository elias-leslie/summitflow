"""Root CLI discovery must remain passive across extracted capability owners."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DISCOVERY_PROBE = r"""
import importlib.abc
import json
import socket
import sys
from pathlib import Path

from typer.testing import CliRunner

argv = json.loads(sys.argv[1])
registry = json.loads((Path.cwd().parent / "scripts/lib/tool-registry.json").read_text())
owner_command_modules = {
    f"cli.commands.{row['namespace']}"
    for row in registry["extensions"]
}
owner_package_roots = {
    "agent_hub_st",
    "browser_automation",
    "code_intelligence",
    "design_tools",
    "desktop_automation",
    "vault_tools",
}


class RejectOwnerImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == root or fullname.startswith(f"{root}.") for root in owner_package_roots):
            raise AssertionError(f"owner implementation imported during discovery: {fullname}")
        if fullname in owner_command_modules:
            raise AssertionError(f"owner CLI shim imported during discovery: {fullname}")
        return None


def reject_connection(_socket, address):
    raise AssertionError(f"service connection attempted during discovery: {address!r}")


sys.meta_path.insert(0, RejectOwnerImports())
socket.socket.connect = reject_connection
socket.socket.connect_ex = reject_connection

from cli.main import app

result = CliRunner().invoke(app, argv)
assert result.exit_code == 0, result.output
assert not any(
    name == root or name.startswith(f"{root}.")
    for name in sys.modules
    for root in owner_package_roots
)
assert owner_command_modules.isdisjoint(sys.modules)
"""


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["tools", "manifest", "--surface", "st.browser", "--format", "json"],
    ],
)
def test_root_discovery_does_not_import_or_contact_capability_owners(argv: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-c", DISCOVERY_PROBE, json.dumps(argv)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_storage_package_preserves_public_reexports() -> None:
    import app.storage as storage
    from app.storage import (
        agent_configs,
        design_assets,
        events,
        explorer,
        explorer_sub_elements,
        explorer_symbols,
    )
    from app.storage.connection import get_connection
    from app.storage.events import (
        create_event,
        get_events_by_trace,
        get_events_with_filters,
        log_task_event,
    )

    assert storage.agent_configs is agent_configs
    assert storage.design_assets is design_assets
    assert storage.events is events
    assert storage.explorer is explorer
    assert storage.explorer_sub_elements is explorer_sub_elements
    assert storage.explorer_symbols is explorer_symbols
    assert storage.get_connection is get_connection
    assert storage.create_event is create_event
    assert storage.get_events_by_trace is get_events_by_trace
    assert storage.get_events_with_filters is get_events_with_filters
    assert storage.log_task_event is log_task_event


@pytest.mark.parametrize(
    "module_name",
    ["explorer_analysis", "explorer_entries", "explorer_sub_elements", "explorer_symbols"],
)
def test_storage_package_preserves_direct_explorer_module_imports(module_name: str) -> None:
    code = """
import importlib
import sys

import app.storage as storage

module_name = sys.argv[1]
resolved = getattr(storage, module_name)
assert resolved is importlib.import_module(f"app.storage.{module_name}")
"""
    result = subprocess.run(
        [sys.executable, "-c", code, module_name],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
