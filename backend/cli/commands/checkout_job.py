"""Private data-only entry point for source jobs running under agent Tether."""

from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from typing import Any

import typer

from app.services.tether import _agent_uid

app = typer.Typer(help="Run an internal agent checkout job.")


def checkout_job(ctx: typer.Context) -> None:
    if os.getuid() != _agent_uid():
        raise SystemExit("Checkout jobs require the configured agent account")
    argv = ctx.args
    if len(argv) != 1:
        raise SystemExit(2)
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise SystemExit(2)
    result: Any = import_module(argv[0]).run_job(payload)
    if not isinstance(result, dict):
        raise TypeError("Checkout job result must be an object")
    print(json.dumps(result))
