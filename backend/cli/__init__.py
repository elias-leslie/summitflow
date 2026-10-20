"""SummitFlow Tasks CLI."""

import os
import shlex
from pathlib import Path


def _load_account_path_defaults() -> None:
    """Load installed literal path settings before CLI imports capture defaults.

    Non-login callers may lack the user manager's environment.d settings. Read
    only ST's two path files, without shell expansion or other environment keys.
    Explicit caller values always win; accounts without config keep defaults.
    """
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "environment.d"
    for filename, key in (("20-st-scratch.conf", "ST_SCRATCH_ROOT"),
                          ("21-st-workspaces.conf", "ST_WORKSPACES_ROOT")):
        if key in os.environ:
            continue
        try:
            lines = (config / filename).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            name, separator, raw = line.partition("=")
            if not separator or name.strip() != key:
                continue
            try:
                values = shlex.split(raw, comments=True)
            except ValueError:
                continue
            if len(values) == 1 and Path(values[0]).is_absolute():
                os.environ.setdefault(key, values[0])


_load_account_path_defaults()
