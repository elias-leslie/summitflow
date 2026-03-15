"""Detect whether CLI is running natively, managing Docker, or inside a container."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

# Compose file path for the SummitFlow ecosystem
COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent / "docker" / "compose"
COMPOSE_FILE = COMPOSE_DIR / "docker-compose.yml"

RuntimeMode = Literal["native", "docker", "container"]


def detect_runtime() -> RuntimeMode:
    """Detect the current runtime environment.

    Returns:
        "container" — running inside a Docker container
        "docker"    — running on host, Docker compose stack is active
        "native"    — running on host, systemd services (no Docker stack)
    """
    # Inside a container?
    if Path("/.dockerenv").exists():
        return "container"

    # Docker compose stack running?
    if not COMPOSE_FILE.exists():
        return "native"

    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "ps",
                "--status",
                "running",
                "-q",
            ],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "docker"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return "native"


def compose_cmd(*args: str) -> list[str]:
    """Build a docker compose command with the ecosystem compose file."""
    return ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
