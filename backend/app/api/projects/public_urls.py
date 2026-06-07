"""Helpers for canonical public project URLs."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

ENV_PUBLIC_BASE_DOMAIN = "SUMMITFLOW_PROJECT_PUBLIC_BASE_DOMAIN"
ENV_PUBLIC_HOST_ALIASES = "SUMMITFLOW_PROJECT_PUBLIC_HOST_ALIASES"
ENV_MANAGED_PROJECTS_ROOT = "SUMMITFLOW_MANAGED_PROJECTS_ROOT"
DEFAULT_MANAGED_PROJECTS_ROOT = str(Path.home() / ".local" / "share" / "summitflow" / "workspaces" / "projects")
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def normalize_project_id(value: str) -> str:
    """Return a stable project slug."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-")


def normalize_url(value: str | None) -> str | None:
    """Trim and de-slash URL-like values."""
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    return normalized or None


@lru_cache(maxsize=1)
def _load_public_url_config() -> tuple[str | None, dict[str, str], str]:
    """Load environment-backed public URL defaults."""
    base_domain = os.getenv(ENV_PUBLIC_BASE_DOMAIN, "").strip().strip("/")
    aliases_text = os.getenv(ENV_PUBLIC_HOST_ALIASES, "").strip()
    managed_root = os.getenv(
        ENV_MANAGED_PROJECTS_ROOT,
        DEFAULT_MANAGED_PROJECTS_ROOT,
    ).rstrip("/")

    aliases: dict[str, str] = {}
    if aliases_text:
        raw_aliases = json.loads(aliases_text)
        if isinstance(raw_aliases, dict):
            aliases = {
                normalize_project_id(str(key)): str(value).strip().strip(".")
                for key, value in raw_aliases.items()
                if str(value).strip()
            }

    return base_domain or None, aliases, managed_root or DEFAULT_MANAGED_PROJECTS_ROOT


def clear_public_url_config_cache() -> None:
    """Clear cached environment-backed URL defaults."""
    _load_public_url_config.cache_clear()


def is_local_url(value: str | None) -> bool:
    """Return whether a URL points at a local or private network target."""
    normalized = normalize_url(value)
    if not normalized:
        return False

    try:
        hostname = urlparse(normalized).hostname
    except ValueError:
        return False
    if not hostname:
        return False

    host = hostname.rstrip(".").lower()
    if host in _LOCAL_HOSTNAMES or host.endswith(".local"):
        return True
    if "." not in host:
        return True

    try:
        candidate = ip_address(host)
    except ValueError:
        return False
    return (
        candidate.is_loopback
        or candidate.is_private
        or candidate.is_link_local
        or candidate.is_reserved
    )


def get_hosted_project_url(
    project_id: str,
    *,
    root_path: str | None = None,
    summitflow_hosted: bool = False,
) -> str | None:
    """Return an env-derived hosted URL when this project should have one."""
    base_domain, aliases, managed_root = _load_public_url_config()
    if not base_domain:
        return None

    normalized_id = normalize_project_id(project_id)
    normalized_root_path = (root_path or "").rstrip("/")
    if not (
        summitflow_hosted
        or normalized_id in aliases
        or normalized_root_path.startswith(f"{managed_root}/")
    ):
        return None

    subdomain = aliases.get(normalized_id, normalized_id)
    return f"https://{subdomain}.{base_domain}" if subdomain else None


def build_project_urls(
    project_id: str,
    *,
    base_url: str | None,
    public_url: str | None,
    root_path: str | None,
    summitflow_hosted: bool = False,
) -> tuple[str | None, str | None]:
    """Build canonical stored base/public URL values for a project."""
    normalized_base_url = normalize_url(base_url)
    normalized_public_url = normalize_url(public_url)
    hosted_url = get_hosted_project_url(
        project_id,
        root_path=root_path,
        summitflow_hosted=summitflow_hosted,
    )

    if normalized_base_url is None:
        normalized_base_url = hosted_url

    if normalized_public_url is None:
        if normalized_base_url and not is_local_url(normalized_base_url):
            normalized_public_url = normalized_base_url
        else:
            normalized_public_url = hosted_url

    return normalized_base_url, normalized_public_url


def resolve_project_public_url(
    project_id: str,
    *,
    base_url: str | None,
    public_url: str | None,
    root_path: str | None,
) -> str:
    """Return the best user-facing app URL for a project response."""
    normalized_public_url = normalize_url(public_url)
    if normalized_public_url:
        return normalized_public_url

    normalized_base_url = normalize_url(base_url)
    if normalized_base_url and not is_local_url(normalized_base_url):
        return normalized_base_url

    hosted_url = get_hosted_project_url(project_id, root_path=root_path)
    return hosted_url or normalized_base_url or ""
