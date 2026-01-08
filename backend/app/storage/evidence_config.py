"""Storage layer for project evidence configuration."""

from __future__ import annotations

import logging
from typing import TypedDict

from psycopg.types.json import Jsonb

from .connection import get_connection

logger = logging.getLogger(__name__)


class ViewportConfig(TypedDict):
    """Viewport configuration for multi-viewport captures."""

    name: str
    width: int
    height: int


class ProjectEvidenceConfig(TypedDict, total=False):
    """Evidence configuration for a project."""

    project_id: str
    enabled_types: list[str]
    capture_schedule: str
    environments: list[str]
    viewports: list[ViewportConfig]
    auto_expand_elements: bool
    regression_threshold: float
    ai_review_enabled: bool


# Default values as standalone constants for type-safe access
DEFAULT_VIEWPORTS: list[ViewportConfig] = [
    {"name": "desktop", "width": 1280, "height": 720},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 390, "height": 844},
]
DEFAULT_ENABLED_TYPES: list[str] = ["screenshot", "console_log"]
DEFAULT_CAPTURE_SCHEDULE: str = "daily"
DEFAULT_ENVIRONMENTS: list[str] = ["local"]
DEFAULT_AUTO_EXPAND: bool = True
DEFAULT_REGRESSION_THRESHOLD: float = 0.05
DEFAULT_AI_REVIEW: bool = False

DEFAULT_EVIDENCE_CONFIG: ProjectEvidenceConfig = {
    "enabled_types": DEFAULT_ENABLED_TYPES,
    "capture_schedule": DEFAULT_CAPTURE_SCHEDULE,
    "environments": DEFAULT_ENVIRONMENTS,
    "viewports": DEFAULT_VIEWPORTS,
    "auto_expand_elements": DEFAULT_AUTO_EXPAND,
    "regression_threshold": DEFAULT_REGRESSION_THRESHOLD,
    "ai_review_enabled": DEFAULT_AI_REVIEW,
}


def get_config(project_id: str) -> ProjectEvidenceConfig:
    """Get evidence configuration for a project.

    Returns default config if none exists.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT enabled_types, capture_schedule, environments, viewports,
                   auto_expand_elements, regression_threshold, ai_review_enabled
            FROM project_evidence_config
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if row is None:
            return {**DEFAULT_EVIDENCE_CONFIG, "project_id": project_id}

        return {
            "project_id": project_id,
            "enabled_types": row[0] or DEFAULT_ENABLED_TYPES,
            "capture_schedule": row[1] or DEFAULT_CAPTURE_SCHEDULE,
            "environments": row[2] or DEFAULT_ENVIRONMENTS,
            "viewports": row[3] or DEFAULT_VIEWPORTS,
            "auto_expand_elements": row[4] if row[4] is not None else DEFAULT_AUTO_EXPAND,
            "regression_threshold": row[5] if row[5] is not None else DEFAULT_REGRESSION_THRESHOLD,
            "ai_review_enabled": row[6] if row[6] is not None else DEFAULT_AI_REVIEW,
        }


def upsert_config(project_id: str, config: ProjectEvidenceConfig) -> ProjectEvidenceConfig:
    """Create or update evidence configuration for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO project_evidence_config (
                project_id, enabled_types, capture_schedule, environments,
                viewports, auto_expand_elements, regression_threshold, ai_review_enabled
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id) DO UPDATE SET
                enabled_types = EXCLUDED.enabled_types,
                capture_schedule = EXCLUDED.capture_schedule,
                environments = EXCLUDED.environments,
                viewports = EXCLUDED.viewports,
                auto_expand_elements = EXCLUDED.auto_expand_elements,
                regression_threshold = EXCLUDED.regression_threshold,
                ai_review_enabled = EXCLUDED.ai_review_enabled,
                updated_at = NOW()
            RETURNING enabled_types, capture_schedule, environments, viewports,
                      auto_expand_elements, regression_threshold, ai_review_enabled
            """,
            (
                project_id,
                config.get("enabled_types", DEFAULT_ENABLED_TYPES),
                config.get("capture_schedule", DEFAULT_CAPTURE_SCHEDULE),
                config.get("environments", DEFAULT_ENVIRONMENTS),
                Jsonb(config.get("viewports", DEFAULT_VIEWPORTS)),
                config.get("auto_expand_elements", DEFAULT_AUTO_EXPAND),
                config.get("regression_threshold", DEFAULT_REGRESSION_THRESHOLD),
                config.get("ai_review_enabled", DEFAULT_AI_REVIEW),
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if row is None:
            return {**config, "project_id": project_id}

        return {
            "project_id": project_id,
            "enabled_types": row[0],
            "capture_schedule": row[1],
            "environments": row[2],
            "viewports": row[3],
            "auto_expand_elements": row[4],
            "regression_threshold": row[5],
            "ai_review_enabled": row[6],
        }


def get_default_config() -> ProjectEvidenceConfig:
    """Return default evidence configuration."""
    return DEFAULT_EVIDENCE_CONFIG.copy()


def get_capability_id_for_entry(project_id: str, explorer_entry_id: int) -> int | None:
    """Get capability_id linked to an explorer entry via explorer_capability_links.

    Used to inherit capability linkage when creating evidence for an explorer entry.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT capability_id FROM explorer_capability_links
            WHERE project_id = %s AND explorer_entry_id = %s
            LIMIT 1
            """,
            (project_id, explorer_entry_id),
        )
        row = cur.fetchone()
        return row[0] if row else None
