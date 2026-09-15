"""Installer target selection must protect the persistent browser VM."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "test-install.sh"


def _select_target(
    tmp_path: Path, args: list[str], settings: dict[str, str], guest_ip: str | None = None
) -> subprocess.CompletedProcess[str]:
    # Execute the real entry point through argument validation, before any API
    # helper or cleanup trap exists. The isolated layout cannot load credentials.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    metadata = tmp_path / "backend" / "cli" / "commands"
    metadata.mkdir(parents=True)
    (metadata / "docker.py").write_text("_BUILD_PROJECTS = []\n")
    source = SCRIPT.read_text()
    prefix = source.split("# ─── Proxmox API helper", 1)[0]
    if guest_ip is not None:
        definitions, main = source.split("# ─── Main", 1)
        addresses = [{"ip-address-type": "ipv4", "ip-address": guest_ip}] if guest_ip else []
        response = json.dumps({"data": {"result": [{"name": "eth0", "ip-addresses": addresses}]}})
        # The actual existing-VM branch runs against a read-only guest-agent
        # fixture. Execution ends before the first SSH connection or reset.
        prefix = (
            definitions
            + f"\npve_api() {{ printf '%s\\n' {shlex.quote(response)}; }}\n# Main"
            + main.split("# Wait for SSH", 1)[0]
            + '\nprintf "HOST:%s\\n" "$VM_IP"\n'
        )
    script = scripts / SCRIPT.name
    script.write_text(prefix + '\nprintf "SELECTED:%s:%s\\n" "$VM_ID" "$EXISTING"\n')
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    (binary_dir / "python").symlink_to(sys.executable)
    env = {
        "PATH": f"{binary_dir}:{os.defpath}",
        "PROXMOX_API_URL": "https://hypervisor.invalid",
        "PROXMOX_TOKEN_ID": "fixture",
        "PROXMOX_TOKEN_SECRET": "fixture",
        "PROXMOX_NODE": "fixture",
        **settings,
    }
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    ("args", "settings"),
    [
        (["--existing"], {}),
        (["--existing"], {"PROXMOX_TEST_VM": "100"}),
        (["--vm-id", "100"], {}),
        (["--vm-id", "0100"], {}),
        (["--existing", "--vm-id", "100"], {}),
        (["--vm-id", "100", "--existing"], {}),
        (["--vm-id", "202"], {"ST_BROWSER_VM_ID": "202"}),
    ],
)
def test_installer_rejects_implicit_or_browser_target(
    tmp_path: Path, args: list[str], settings: dict[str, str]
) -> None:
    result = _select_target(tmp_path, args, settings)
    assert result.returncode != 0, result.stdout
    assert "SELECTED:" not in result.stdout
    assert "browser" in result.stderr or "explicit" in result.stderr


@pytest.mark.parametrize(
    ("args", "settings", "selection"),
    [
        ([], {}, "101:false"),
        (["--existing"], {"PROXMOX_TEST_VM": "202"}, "202:true"),
        (["--existing", "--vm-id", "202"], {"PROXMOX_TEST_VM": "100"}, "202:true"),
        (["--vm-id", "202", "--existing"], {"PROXMOX_TEST_VM": "100"}, "202:true"),
    ],
)
def test_installer_keeps_explicit_test_target_independent_of_argument_order(
    tmp_path: Path, args: list[str], settings: dict[str, str], selection: str
) -> None:
    result = _select_target(tmp_path, args, settings)
    assert result.returncode == 0, result.stderr
    assert f"SELECTED:{selection}" in result.stdout


@pytest.mark.parametrize(
    ("guest_ip", "settings", "accepted"),
    [
        ("192.0.2.202", {}, True),
        ("192.0.2.202", {"TEST_VM_HOST": "192.0.2.202"}, True),
        ("192.0.2.202", {"TEST_VM_HOST": "192.0.2.100"}, False),
        ("", {"TEST_VM_HOST": "192.0.2.100"}, False),
    ],
)
def test_existing_installer_binds_ssh_address_to_selected_guest(
    tmp_path: Path, guest_ip: str, settings: dict[str, str], accepted: bool
) -> None:
    result = _select_target(tmp_path, ["--existing", "--vm-id", "202"], settings, guest_ip)
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    if accepted:
        assert f"HOST:{guest_ip}" in result.stdout
    else:
        assert "refusing reset" in result.stderr
        assert "SELECTED:" not in result.stdout
