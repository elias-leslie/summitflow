"""PROXMOX_CA_BUNDLE pins TLS to the PVE cluster CA for the runtime status API and the st vm client."""

from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.api import _runtime_proxmox as runtime
from cli.lib import proxmox


@pytest.fixture
def ca_file(tmp_path):
    # A throwaway self-signed CA stands in for the PVE cluster CA, so the test never skips.
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture PVE CA")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    path = tmp_path / "pve-ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path)


def test_runtime_context_pins_ca_even_when_verify_flag_is_off(monkeypatch, ca_file):
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", ca_file)
    ctx = runtime._ssl_context(False)
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
    assert isinstance(proxmox._verify_arg(ca_file), ssl.SSLContext) and proxmox._verify_arg(False) is False


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
