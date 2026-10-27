"""Generate the per-project `.index.yaml` runtime map read by agents and Agent Hub.

Keys: project, generated_at, environment, services, urls, network, pages. Everything is
derived live from the project registration and checkout; nothing is cached in the database.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ...logging_config import get_logger
from ...utils import safe_subprocess
from ._project import get_project_config, get_project_root
from .environment import get_environment
from .pages import discover_pages
from .port_detection import get_services

logger = get_logger(__name__)

INDEX_FILENAME = ".index.yaml"


def get_project_urls(project_id: str, services: dict[str, Any]) -> dict[str, str]:
    """Get project URLs from detected ports (preferred) or the registered base_url.

    Port-derived localhost URLs take precedence over base_url to avoid stale
    or environment-specific values (e.g. Proxmox IPs, production domains).
    """
    urls: dict[str, str] = {}

    frontend_port = services.get("frontend_port")
    if frontend_port:
        urls["frontend"] = f"http://localhost:{frontend_port}"
    else:
        base_url = (get_project_config(project_id) or {}).get("base_url")
        if isinstance(base_url, str) and base_url:
            urls["frontend"] = base_url.rstrip("/")

    backend_port = services.get("backend_port")
    if backend_port:
        urls["api"] = f"http://localhost:{backend_port}/api"

    return urls


def get_network_info() -> dict[str, str]:
    """Get host network identity for cross-machine URL construction.

    Returns host_ip (first LAN address) and hostname so agents can build
    URLs reachable from remote browser verification hosts.
    """
    info: dict[str, str] = {}
    try:
        result = safe_subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            info["host_ip"] = result.stdout.strip().split()[0]
    except (OSError, subprocess.TimeoutExpired):
        pass
    with contextlib.suppress(OSError):
        info["hostname"] = socket.gethostname()
    return info


def _page_line(page: dict[str, Any]) -> str:
    """Render a page as ``path`` or ``path (name)`` when the name adds information."""
    path, name = page["path"], page["name"]
    if path == "/" or not name or path.rstrip("/").endswith(f"/{name}"):
        return path
    return f"{path} ({name})"


def generate_index(project_id: str) -> str:
    """Generate the `.index.yaml` content for a project."""
    services = get_services(project_id)
    index_data: dict[str, Any] = {
        "project": project_id,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    for key, value in (
        ("environment", get_environment(project_id)),
        ("services", services),
        ("urls", get_project_urls(project_id, services)),
        ("network", get_network_info()),
        ("pages", [_page_line(page) for page in discover_pages(project_id)]),
    ):
        if value:
            index_data[key] = value
    return yaml.dump(index_data, default_flow_style=False, sort_keys=False)


def _index_content(content: str) -> Any:
    """Compare semantic index data without the generation timestamp."""
    try:
        value = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if isinstance(value, dict):
        value.pop("generated_at", None)
    return value


def _exclude_generated_index(index_path: Path) -> None:
    """Keep generated metadata local; Git still reports intentionally tracked indexes."""
    result = safe_subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-path", "info/exclude"],
        cwd=index_path.parent, capture_output=True, text=True, timeout=5, check=False,
    )
    if result.returncode != 0:
        return  # Non-Git projects retain the same index generation contract.
    root, exclude_path = result.stdout.splitlines()
    relative_path = (index_path.parent.resolve() / index_path.name).relative_to(root).as_posix()
    # Paths in Git ignore files are patterns, even when the filename is literal.
    rule = "/" + "".join("\\" + char if char in "\\*?[] " else char for char in relative_path)
    exclude = Path(exclude_path)
    previous = exclude.read_text() if exclude.exists() else ""
    if rule not in previous.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as stream:
            stream.write(("\n" if previous and not previous.endswith("\n") else "") + rule + "\n")


def write_index_file(project_id: str) -> str | None:
    """Generate and write `.index.yaml` to the project root; return its path or None."""
    root_path = get_project_root(project_id)
    if not root_path:
        logger.warning("No root path found for project %s", project_id)
        return None
    index_path = Path(root_path) / INDEX_FILENAME
    tmp_path = index_path.with_name(f"{index_path.name}.tmp")
    try:
        _exclude_generated_index(index_path)
        generated = generate_index(project_id)
        # Keep the last material snapshot byte-for-byte when only the timestamp moves.
        if index_path.exists() and _index_content(index_path.read_text()) == _index_content(generated):
            return str(index_path)
        tmp_path.write_text(generated)
        tmp_path.rename(index_path)
        logger.info("Wrote index file: %s", index_path)
        return str(index_path)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.error("Failed to write index file %s: %s", index_path, e)
        return None


def write_all_index_files() -> dict[str, str | None]:
    """Write `.index.yaml` for every registered, unretired, non-testing project with a root."""
    from ...storage.connection import get_cursor
    from ...storage.projects import testing_project_ids

    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM projects WHERE root_path IS NOT NULL "
            "AND id NOT IN (SELECT project_id FROM project_retirement_decisions) ORDER BY id"
        )
        rows = cur.fetchall()
    excluded = testing_project_ids()
    results: dict[str, str | None] = {}
    for (project_id,) in rows:
        if project_id in excluded:
            continue
        try:
            results[project_id] = write_index_file(project_id)
        except Exception as e:
            logger.error("Failed to generate index for %s: %s", project_id, e)
            results[project_id] = None
    return results
