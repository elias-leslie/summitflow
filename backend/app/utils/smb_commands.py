"""Bounded smbclient command grammar (not shell quoting).

smbclient splits -c at every semicolon, even inside quotes. Only this builder
may introduce separators; tokens exclude quotes, escapes, controls and globs.
"""
from __future__ import annotations

import re
from collections.abc import Sequence


class SmbCommandError(ValueError):
    """Configuration cannot be represented safely in smbclient's grammar."""


def smb_path(value: object, *, filename: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise SmbCommandError("Invalid SMB path")
    # Keep normal Unicode names and spaces, but no interpreter syntax.
    if any(not (char.isalnum() or char in " /._-@()+,$") for char in value):
        raise SmbCommandError("Unsupported SMB path characters")
    parts = value.strip("/").split("/")
    if filename and ("/" in value or value in {".", ".."}):
        raise SmbCommandError("Invalid SMB filename")
    if value not in {".", "/"} and any(
        not part.strip() or part != part.strip() or part.endswith(".")
        or part in {".", ".."} or len(part.encode("utf-8")) > 255
        for part in parts
    ):
        raise SmbCommandError("Invalid SMB path components")
    return value


def smb_service(host: object, share: object) -> str:
    if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", host):
        raise SmbCommandError("Invalid SMB host")
    return f"//{host}/{smb_path(share, filename=True)}"


def smb_command(*commands: Sequence[str]) -> str:
    rendered: list[str] = []
    for command in commands:
        if not command:
            raise SmbCommandError("Invalid SMB operation")
        op, *args = command
        if op in {"cd", "mkdir"} and len(args) == 1:
            values = [smb_path(args[0])]
        elif op == "ls" and len(args) in {0, 1}:
            values = [smb_path(arg, filename=True) for arg in args]
        elif op in {"put", "get"} and len(args) == 2:
            local, remote = args if op == "put" else args[::-1]
            smb_path(local)
            smb_path(remote, filename=True)
            values = args
        else:
            raise SmbCommandError("Invalid SMB operation")
        rendered.append(" ".join([op, *(f'"{value}"' for value in values)]))
    if not rendered:
        raise SmbCommandError("Missing SMB operation")
    return "; ".join(rendered)


def smb_archive_location(location: str) -> tuple[str, str, str]:
    if not isinstance(location, str) or not location.startswith("//"):
        raise SmbCommandError("Invalid SMB archive location")
    parts = location[2:].split("/")
    if len(parts) < 3:
        raise SmbCommandError("Invalid SMB archive location")
    service = smb_service(parts[0], parts[1])
    directory = "/".join(parts[2:-1]) or "."
    return service, smb_path(directory), smb_path(parts[-1], filename=True)
