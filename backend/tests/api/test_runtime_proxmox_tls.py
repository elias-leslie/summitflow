"""Every PVE API client pins TLS to the PVE cluster CA (PROXMOX_CA_BUNDLE); an unset or missing CA refuses the call."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib import error as urllib_error

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException

from app.api import _runtime_proxmox as runtime
from cli.lib import proxmox

_PVE_ENV = {"PROXMOX_API_URL": "https://pve:8006", "PROXMOX_TOKEN_ID": "u@pve!t", "PROXMOX_TOKEN_SECRET": "s",
            "PROXMOX_NODE": "n"}


def _issue(name: str, issuer: tuple[x509.Name, ec.EllipticCurvePrivateKey] | None = None):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    issuer_name, issuer_key = issuer or (subject, key)
    now = datetime.now(UTC)
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
               .not_valid_after(now + timedelta(days=1)))
    if issuer is None:
        builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    else:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
    return subject, key, builder.sign(issuer_key, hashes.SHA256())


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.fixture
def ca_file(tmp_path):
    # A throwaway self-signed CA stands in for the PVE cluster CA, so the test never skips.
    _name, _key, cert = _issue("Fixture PVE CA")
    path = tmp_path / "pve-ca.pem"
    path.write_bytes(_pem(cert))
    return str(path)


@pytest.fixture
def pve_server(tmp_path):
    """A local HTTPS 'PVE API' whose certificate the pinned CA issued, plus an unrelated CA file."""
    ca_name, ca_key, ca_cert = _issue("Pinned PVE CA")
    _other_name, _other_key, other_cert = _issue("Some other CA")
    _leaf_name, leaf_key, leaf_cert = _issue("pve", (ca_name, ca_key))
    (tmp_path / "pinned.pem").write_bytes(_pem(ca_cert))
    (tmp_path / "other.pem").write_bytes(_pem(other_cert))
    (tmp_path / "leaf.pem").write_bytes(_pem(leaf_cert))
    (tmp_path / "leaf.key").write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                               serialization.NoEncryption()))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"node": "n", "status": "online"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "leaf.pem", tmp_path / "leaf.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_address[1]}", str(tmp_path / "pinned.pem"), str(tmp_path / "other.pem")
    server.shutdown()
    server.server_close()


def test_pinned_context_verifies_chain_and_hostname(ca_file):
    ctx = runtime.pinned_ca_context(ca_file)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT


@pytest.mark.parametrize("ca_bundle", ["", "   ", "/nonexistent/ca.pem"])
def test_unset_or_missing_ca_raises_whatever_verify_ssl_says(monkeypatch, ca_bundle):
    # Bypass attempt: the old PROXMOX_VERIFY_SSL=false escape hatch no longer exists.
    monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", ca_bundle)
    with pytest.raises(runtime.ProxmoxTLSConfigError, match="PROXMOX_CA_BUNDLE"):
        runtime._ssl_context()
    with pytest.raises(runtime.ProxmoxTLSConfigError):
        runtime.pinned_ca_context(ca_bundle)


def test_runtime_status_reports_missing_ca_without_calling_pve(monkeypatch):
    for key, value in _PVE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PROXMOX_CA_BUNDLE", raising=False)
    opened: list[object] = []
    monkeypatch.setattr(runtime.urllib_request, "urlopen", lambda *args, **kwargs: opened.append(args))
    status = asyncio.run(runtime.get_proxmox_status())
    assert status.reachable is False and "PROXMOX_CA_BUNDLE" in (status.error or "")
    with pytest.raises(HTTPException) as refused:
        asyncio.run(runtime.control_proxmox_guest("n", "qemu", 101, "start"))
    assert refused.value.status_code == 502 and "PROXMOX_CA_BUNDLE" in str(refused.value.detail)
    assert opened == []


def test_runtime_client_accepts_the_pinned_ca_and_refuses_another(monkeypatch, pve_server):
    url, pinned, other = pve_server
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", pinned)
    assert runtime._sync_proxmox_get_json(url, "u@pve!t", "s", "/cluster/resources?type=node") == [{"node": "n", "status": "online"}]
    # Bypass attempt: a server whose certificate the pinned CA did not issue never gets the token.
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", other)
    with pytest.raises(urllib_error.URLError) as refused:
        runtime._sync_proxmox_get_json(url, "u@pve!t", "s", "/cluster/resources?type=node")
    assert isinstance(refused.value.reason, ssl.SSLCertVerificationError)


def test_cli_client_accepts_the_pinned_ca_and_refuses_another(pve_server):
    url, pinned, other = pve_server
    client = proxmox.ProxmoxClient(proxmox.ProxmoxConfig(url, "u@pve!t", "s", "n", ca_bundle=pinned))
    assert client.request("GET", "/cluster/resources?type=node") == [{"node": "n", "status": "online"}]
    other_client = proxmox.ProxmoxClient(proxmox.ProxmoxConfig(url, "u@pve!t", "s", "n", ca_bundle=other))
    with pytest.raises(proxmox.ProxmoxError, match=r"CERTIFICATE_VERIFY_FAILED|certificate verify failed"):
        other_client.request("GET", "/cluster/resources?type=node")


def test_cli_config_requires_the_ca(monkeypatch, ca_file):
    for key, value in _PVE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", ca_file)
    assert proxmox.load_proxmox_config().ca_bundle == ca_file
    monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")
    for missing in ("", "/nonexistent/ca.pem"):
        monkeypatch.setenv("PROXMOX_CA_BUNDLE", missing)
        with pytest.raises(proxmox.ProxmoxError, match="PROXMOX_CA_BUNDLE"):
            proxmox.load_proxmox_config()


def test_cli_client_without_ca_never_sends_the_token(monkeypatch):
    sent: list[object] = []
    monkeypatch.setattr(proxmox.httpx, "request", lambda *args, **kwargs: sent.append(args))
    client = proxmox.ProxmoxClient(proxmox.ProxmoxConfig("https://pve:8006", "u@pve!t", "s", "n"))
    with pytest.raises(proxmox.ProxmoxError, match="PROXMOX_CA_BUNDLE"):
        client.request("GET", "/version")
    assert sent == []


def test_cli_config_reads_host_env_local_when_shell_has_no_proxmox_env(tmp_path, monkeypatch, ca_file) -> None:
    for key in ("PROXMOX_API_URL", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                "PROXMOX_CA_BUNDLE", "PROXMOX_VERIFY_SSL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(proxmox, "get_repo_root", lambda: tmp_path / "repo")
    (tmp_path / ".env.local").write_text(
        "PROXMOX_API_URL=https://pve:8006\nPROXMOX_TOKEN_ID=u@pve!t\nPROXMOX_TOKEN_SECRET=s\n"
        f"PROXMOX_NODE=n\nPROXMOX_CA_BUNDLE={ca_file}\nUNRELATED=ignored\n"
    )
    config = proxmox.load_proxmox_config()
    assert (config.host, config.node, config.ca_bundle) == ("https://pve:8006", "n", ca_file)
