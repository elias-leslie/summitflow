"""Transient title forwarding through the generic local owner root contract."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx

RootSurface = Literal["aico", "a-term"]
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_GENERATION = re.compile(r"[0-9a-f]{64}\Z")
_RESPONSE_LIMIT = 16 * 1024


def _label(value: str) -> str:
    label = value.strip()
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF
           or char in "\u2028\u2029" for char in label):
        raise ValueError("Label requires control-free single-line Unicode")
    if not label or len(label.encode("utf-8")) > 160:
        raise ValueError("Label requires 1-160 trimmed UTF-8 bytes")
    return label


def _owner_client(surface: RootSurface) -> httpx.Client:
    if surface == "aico":
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        socket = os.environ.get("AICO_GUI_CONTROL_SOCKET", f"{runtime}/aico/gui-control.sock")
        if (not os.path.isabs(socket) or len(os.fsencode(socket)) > 107
                or any(part in {"", ".", ".."} for part in socket.split("/")[1:])
                or any(not char.isprintable() for char in socket)):
            raise ValueError("Invalid local owner socket configuration")
        return httpx.Client(base_url="http://aico", transport=httpx.HTTPTransport(uds=socket), timeout=5, trust_env=False)
    base = os.environ.get("A_TERM_ROOT_CONTROL_URL", "http://127.0.0.1:8002").rstrip("/")
    try:
        parsed = urlsplit(base)
        valid = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                 and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                 and parsed.path == "" and parsed.port is not None)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("A-Term requires the configured loopback owner route")
    # Preserve the owner's configured auth rejection, without supplying credentials.
    return httpx.Client(base_url=base, timeout=5, trust_env=False)


def _request(client: httpx.Client, method: str, path: str, payload: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        with client.stream(method, path, json=payload) as response:
            if response.status_code != 200:
                reason = {401: "Owner authentication required", 403: "Owner access denied",
                          404: "Exact owner root not found", 409: "Owner generation or workload changed",
                          410: "Owner root ended"}.get(response.status_code, "Owner title operation unavailable")
                raise ValueError(reason)
            body = bytearray()
            for part in response.iter_bytes():
                body.extend(part)
                if len(body) > _RESPONSE_LIMIT:
                    raise ValueError("Owner acknowledgment unavailable")
            result = json.loads(body)
    except (httpx.HTTPError, OSError):
        raise ValueError("Local owner unavailable; title outcome unconfirmed") from None
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("Owner acknowledgment unavailable") from None
    if not isinstance(result, dict):
        raise ValueError("Owner acknowledgment unavailable")
    return result


def title_root(root: str, label: str, *, surface: RootSurface = "aico") -> dict[str, Any]:
    """Read and fence one exact retained owner root; retain no content locally."""
    if not _KEY.fullmatch(root):
        raise ValueError("Root requires an exact retained request ID")
    if surface not in {"aico", "a-term"}:
        raise ValueError("Unsupported root surface")
    label = _label(label)
    path = f"/v1/roots/{quote(root, safe='')}"
    with _owner_client(surface) as client:
        descriptor = _request(client, "GET", path)
        generation = descriptor.get("generation")
        identity = ("owner", "requestId", "hostIdentity", "logicalSessionId", "surfaceLocator", "generation")
        if (descriptor.get("owner") != surface or descriptor.get("requestId") != root
                or descriptor.get("status") != "running" or not isinstance(generation, str)
                or not _GENERATION.fullmatch(generation)
                or any(not isinstance(descriptor.get(key), str) or not descriptor[key] for key in identity)):
            raise ValueError("Exact running owner root unavailable")
        result = _request(client, "POST", path + "/title", {"generation": generation, "label": label})
        if result.get("status") != "running" or any(result.get(key) != descriptor[key] for key in identity):
            raise ValueError("Owner title acknowledgment unconfirmed; reconcile the exact root")
    # Unrelated owner fields, including title content, never leave this boundary.
    return {"root": root, "owner": surface, "generation": generation, "status": "running", "applied": True}
