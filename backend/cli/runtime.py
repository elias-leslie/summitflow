"""Detect whether CLI is running natively, managing Docker, or inside a container."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

# Compose file path for the SummitFlow ecosystem
COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent / "docker" / "compose"
COMPOSE_FILE = COMPOSE_DIR / "docker-compose.yml"
COMPOSE_DEV_FILE = COMPOSE_DIR / "docker-compose.dev.yml"
COMPOSE_ENV_FILE = COMPOSE_DIR / ".env"
RUNTIME_MODE_FILE = COMPOSE_DIR / ".runtime-mode"
DEFAULT_DOCKER_MODE = os.environ.get("SUMMITFLOW_DOCKER_DEFAULT_MODE", "dev")
if DEFAULT_DOCKER_MODE not in {"dev", "prod"}:
    DEFAULT_DOCKER_MODE = "dev"

RuntimeMode = Literal["native", "docker", "container"]
DockerMode = Literal["dev", "prod"]


def compose_env() -> dict[str, str]:
    """Build a compose subprocess environment from the host env.

    Keys defined in the canonical compose `.env` file are stripped from the
    inherited process environment so Docker Compose cannot override the file
    source with stale values from long-lived shells or tmux sessions.
    """
    env = os.environ.copy()
    if COMPOSE_ENV_FILE.exists():
        for raw_line in COMPOSE_ENV_FILE.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key:
                env.pop(key, None)
    return env


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
            compose_cmd("ps", "--status", "running", "-q"),
            env=compose_env(),
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
    cmd = ["docker", "compose"]
    if COMPOSE_ENV_FILE.exists():
        cmd.extend(["--env-file", str(COMPOSE_ENV_FILE)])
    cmd.extend(["-f", str(COMPOSE_FILE), *args])
    return cmd


def read_docker_mode() -> DockerMode:
    """Read the saved Docker mode, falling back to the default."""
    if RUNTIME_MODE_FILE.exists():
        raw = RUNTIME_MODE_FILE.read_text().strip()
        if raw in {"dev", "prod"}:
            return raw
    return DEFAULT_DOCKER_MODE


def write_docker_mode(mode: DockerMode) -> None:
    """Persist the selected Docker mode."""
    COMPOSE_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_MODE_FILE.write_text(f"{mode}\n")


def compose_cmd_for_mode(mode: DockerMode, *args: str) -> list[str]:
    """Build a docker compose command for a specific Docker mode."""
    files = ["docker", "compose"]
    if COMPOSE_ENV_FILE.exists():
        files.extend(["--env-file", str(COMPOSE_ENV_FILE)])
    files.extend(["-f", str(COMPOSE_FILE)])
    if mode == "dev" and COMPOSE_DEV_FILE.exists():
        files.extend(["-f", str(COMPOSE_DEV_FILE)])
    files.extend(args)
    return files
