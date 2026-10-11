"""PROXMOX_CA_BUNDLE pins TLS to the PVE cluster CA for the runtime status API and the st vm client."""

from __future__ import annotations

import ssl

import pytest

from app.api import _runtime_proxmox as runtime
from cli.lib import proxmox


@pytest.fixture
def ca_file(tmp_path):
    # any valid PEM works for the context; use the system default CA file when present
    path = ssl.get_default_verify_paths().cafile
    if not path:
        pytest.skip("no system CA file to stand in for the PVE CA")
    return path


def test_runtime_context_pins_ca_even_when_verify_flag_is_off(monkeypatch, ca_file):
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", ca_file)
    ctx = runtime._ssl_context(False)
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_runtime_context_legacy_behavior_without_ca(monkeypatch):
    monkeypatch.delenv("PROXMOX_CA_BUNDLE", raising=False)
    assert runtime._ssl_context(True) is None
    off = runtime._ssl_context(False)
    assert off is not None and off.verify_mode == ssl.CERT_NONE
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", "/nonexistent/ca.pem")
    missing = runtime._ssl_context(False)
    assert missing is not None and missing.verify_mode == ssl.CERT_NONE


def test_cli_config_verify(monkeypatch, ca_file):
    for key, value in {"PROXMOX_API_URL": "https://pve:8006", "PROXMOX_TOKEN_ID": "u@pve!t", "PROXMOX_TOKEN_SECRET": "s",
                       "PROXMOX_NODE": "n"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", ca_file)
    assert proxmox.load_proxmox_config().verify == ca_file
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", "")
    monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")
    assert proxmox.load_proxmox_config().verify is False
