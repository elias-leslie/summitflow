#!/usr/bin/env python3
"""Explicit managed Codex App Server stdio entrypoint; feature flag defaults off."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from codex_managed_capture import capture_enabled, codex_binary, supervise
from codex_managed_delivery import (
    configured_outbox,
    configured_path,
    operator_action,
    operator_status,
)
from codex_managed_outbox import OutboxFull


def native_fallback(binary: str, project_id: str | None = None):
    """A configured owner lock still fences duplicate launch when policy parsing fails."""
    path = configured_path(project_id)
    if path:
        directory = Path(path).parent
        if directory.exists():
            info = directory.lstat()
            if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700:
                fd = os.open(str(path) + ".owner-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    os.set_inheritable(fd, True)
                    os.execv(binary, [binary, "app-server", "--listen", "stdio://"])
                finally:
                    os.close(fd)
    os.execv(binary, [binary, "app-server", "--listen", "stdio://"])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--disable-capture", action="store_true")
    parser.add_argument("--enable-capture", action="store_true")
    parser.add_argument("--update-action", choices=["check-update", "stage-update", "qualify-update", "promote-update", "rollback-update"])
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    identity = json.loads((root / "project.identity.json").read_text())
    if identity["project"]["id"] != args.project or not Path.cwd().resolve().is_relative_to(root):
        raise ValueError("managed_project_binding_mismatch")
    if args.status or args.drain or args.disable_capture or args.enable_capture or args.update_action:
        if args.disable_capture and args.enable_capture:
            raise ValueError("managed_capture_switch_conflict")
        action = args.update_action or ("disable" if args.disable_capture else "enable" if args.enable_capture else "drain" if args.drain else None)
        status = operator_action(action, project_id=args.project) if action else operator_status(project_id=args.project)
        print(json.dumps(status))
        return 0
    binary = codex_binary()
    if not capture_enabled():
        # No spool/schema/service dependency in rollback mode. The existing
        # transcript collector continues to observe this ordinary native process.
        os.execv(binary, [binary, "app-server", "--listen", "stdio://"])
    try:
        outbox = configured_outbox(args.project)
    except (OSError, sqlite3.Error, KeyError, ValueError, OutboxFull) as error:
        if isinstance(error, ValueError) and str(error) == "managed_outbox_project_binding_mismatch":
            raise
        print("Managed Codex durable storage unavailable; native execution continues with rollout recovery.", file=sys.stderr)
        native_fallback(binary, args.project)
    if outbox is None:
        print("Managed Codex outbox configuration unavailable; native execution continues with rollout recovery.", file=sys.stderr)
        native_fallback(binary, args.project)
    from codex_managed_update import selected_binary

    try:
        binary = selected_binary(outbox) or binary
    except (OSError, sqlite3.Error, ValueError):
        print("Managed Codex selected runtime unavailable; native execution continues with rollout recovery.", file=sys.stderr)
        native_fallback(binary, args.project)
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    namespace = f"{os.uname().nodename}:{codex_home}"
    return supervise(outbox, project=args.project, namespace=namespace, binary=binary, input_stream=sys.stdin.buffer, output_stream=sys.stdout.buffer)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:
        print("Managed Codex capture failed; inspect content-free outbox health and recover through rollout sync.", file=sys.stderr)
        raise SystemExit(2) from None
