#!/usr/bin/env python3
"""Explicit managed Codex App Server stdio entrypoint; feature flag defaults off."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from codex_managed_capture import capture_enabled, codex_binary, supervise
from codex_managed_delivery import configured_outbox, recover_configured_outbox


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--disable-capture", action="store_true")
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    identity = json.loads((root / "project.identity.json").read_text())
    if identity["project"]["id"] != args.project or not Path.cwd().resolve().is_relative_to(root):
        raise ValueError("managed_project_binding_mismatch")
    if args.status or args.drain or args.disable_capture:
        outbox = configured_outbox()
        if args.disable_capture and outbox:
            outbox.disable_capture()
        status = recover_configured_outbox(os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")) if args.drain else outbox.status() if outbox else {"health": "rollout_only"}
        print(json.dumps(status))
        return 0
    binary = codex_binary()
    if not capture_enabled():
        # No spool/schema/service dependency in rollback mode. The existing
        # transcript collector continues to observe this ordinary native process.
        os.execv(binary, [binary, "app-server", "--listen", "stdio://"])
    outbox = configured_outbox()
    if outbox is None:
        raise ValueError("managed_outbox_configuration_required")
    if outbox.owner()["capture_disabled"]:
        os.execv(binary, [binary, "app-server", "--listen", "stdio://"])
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    namespace = f"{os.uname().nodename}:{codex_home}"
    return supervise(outbox, project=args.project, namespace=namespace, binary=binary, input_stream=sys.stdin.buffer, output_stream=sys.stdout.buffer)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:
        print("Managed Codex capture failed; inspect content-free outbox health and recover through rollout sync.", file=sys.stderr)
        raise SystemExit(2) from None
