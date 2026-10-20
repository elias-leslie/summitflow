"""Which SummitFlow identity token this user presents."""

from __future__ import annotations

import os
from pathlib import Path

# (env var naming the token file, default file under HOME, header). The server reads the same files.
_TOKEN_SOURCES = (
    ("SUMMITFLOW_OWNER_TOKEN_FILE", ".config/credstore/summitflow/owner-token", "X-SummitFlow-Owner-Token"),
    ("SUMMITFLOW_AGENT_TOKEN_FILE", ".config/agent-tokens/summitflow", "X-SummitFlow-Agent-Token"),
)


def token_headers() -> dict[str, str]:
    """The caller's SummitFlow token header: the owner token if its file is readable, else the agent token.

    Each file is the env var's path or its default under HOME; file modes keep the other user's token unreadable.
    """
    for env_name, default_path, header in _TOKEN_SOURCES:
        path = os.environ.get(env_name, "").strip() or str(Path.home() / default_path)
        try:
            token = Path(path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if token:
            return {header: token}
    return {}
