"""add_project_public_url

Revision ID: c68eb0a27edb
Revises: 70872a5bb120
Create Date: 2026-04-04 13:17:09.878178

"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c68eb0a27edb"
down_revision: str | Sequence[str] | None = "70872a5bb120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENV_PUBLIC_BASE_DOMAIN = "SUMMITFLOW_PROJECT_PUBLIC_BASE_DOMAIN"
_ENV_PUBLIC_HOST_ALIASES = "SUMMITFLOW_PROJECT_PUBLIC_HOST_ALIASES"
_ENV_MANAGED_PROJECTS_ROOT = "SUMMITFLOW_MANAGED_PROJECTS_ROOT"
_DEFAULT_MANAGED_PROJECTS_ROOT = str(Path.home() / ".local" / "share" / "summitflow" / "workspaces" / "projects")
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _normalize_project_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-")


def _normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    return normalized or None


def _is_local_url(value: str | None) -> bool:
    normalized = _normalize_url(value)
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


def _get_hosted_url(project_id: str, root_path: str | None) -> str | None:
    base_domain = os.getenv(_ENV_PUBLIC_BASE_DOMAIN, "").strip().strip("/")
    if not base_domain:
        return None

    aliases_text = os.getenv(_ENV_PUBLIC_HOST_ALIASES, "").strip()
    aliases: dict[str, str] = {}
    if aliases_text:
        raw_aliases = json.loads(aliases_text)
        if isinstance(raw_aliases, dict):
            aliases = {
                _normalize_project_id(str(key)): str(value).strip().strip(".")
                for key, value in raw_aliases.items()
                if str(value).strip()
            }

    managed_root = os.getenv(
        _ENV_MANAGED_PROJECTS_ROOT,
        _DEFAULT_MANAGED_PROJECTS_ROOT,
    ).rstrip("/")
    normalized_id = _normalize_project_id(project_id)
    normalized_root_path = (root_path or "").rstrip("/")
    if not (
        normalized_id in aliases
        or normalized_root_path.startswith(f"{managed_root}/")
    ):
        return None

    subdomain = aliases.get(normalized_id, normalized_id)
    return f"https://{subdomain}.{base_domain}" if subdomain else None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("projects", sa.Column("public_url", sa.Text(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, base_url, root_path FROM projects")
    ).fetchall()
    for row in rows:
        project_id = str(row[0])
        base_url = _normalize_url(row[1])
        root_path = row[2]

        if base_url and not _is_local_url(base_url):
            public_url = base_url
        else:
            public_url = _get_hosted_url(project_id, root_path)

        if public_url:
            connection.execute(
                sa.text(
                    "UPDATE projects SET public_url = :public_url WHERE id = :project_id"
                ),
                {"project_id": project_id, "public_url": public_url},
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("projects", "public_url")
