"""Registry of SummitFlow cron workflows and the agent-config flags that gate them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.storage.agent_configs import get_agent_config

ScheduleScope = Literal["project", "system"]
SUMMITFLOW_CONTROL_PROJECT_ID = "summitflow"


@dataclass(frozen=True)
class ScheduleDefinition:
    """Config-backed schedule metadata."""

    schedule_id: str
    config_key: str
    label: str
    description: str
    cron: str
    scope: ScheduleScope
    default_enabled: bool = True


SCHEDULE_DEFINITIONS: tuple[ScheduleDefinition, ...] = (
    ScheduleDefinition(
        schedule_id="reset_claims",
        config_key="reset_claims_enabled",
        label="Claim reset",
        description="Clears expired task claims so stuck work can be retried intentionally.",
        cron="*/15 * * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="scan_projects",
        config_key="scan_projects_enabled",
        label="Project scan",
        description="Refreshes explorer scans across projects.",
        cron="0 */6 * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="dependency_reviews",
        config_key="dependency_reviews_enabled",
        label="Dependency reviews",
        description="Checks direct packages weekly and reviews newly observed advisories without installing updates.",
        cron="45 */6 * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="refresh_precision_indexes",
        config_key="refresh_precision_indexes_enabled",
        label="Precision index refresh",
        description="Rebuilds precision search indexes for symbol-first context retrieval.",
        cron="10 3 * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="refresh_graphify_graphs",
        config_key="refresh_graphify_graphs_enabled",
        label="Graphify graph refresh",
        description="Refreshes stale existing Graphify code graphs for topology retrieval.",
        cron="25 */2 * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="scheduled_backups",
        config_key="scheduled_backups_enabled",
        label="Backup health check",
        description="Checks that both backup layers are current and tidies old records. The backups themselves run from systemd every 4 hours.",
        cron="30 * * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="stale_cleanup",
        config_key="stale_cleanup_enabled",
        label="Stale cleanup",
        description="Runs daily maintenance and stale cleanup tasks.",
        cron="0 4 * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="hatchet_retention",
        config_key="hatchet_retention_enabled",
        label="Hatchet retention guard",
        description="Prunes Hatchet OLAP and lookup tables after a backup using the Hatchet tenant retention period.",
        cron="45 4 * * 0",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="prod_smoke_test",
        config_key="prod_smoke_test_enabled",
        label="Production smoke test",
        description="Runs the lightweight production smoke suite and only notifies on state changes.",
        cron="*/30 * * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="health_monitor",
        config_key="health_monitor_enabled",
        label="Health monitor",
        description="Performs frequent health checks and notifications.",
        cron="*/5 * * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="nightly_publication",
        config_key="nightly_publication_enabled",
        label="Hourly publication",
        description="Pushes each auto-published project to GitHub every hour: private repos their committed head, public repos their newest accepted commit.",
        cron="5 * * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="nightly_deep_lane",
        config_key="nightly_deep_lane_enabled",
        label="Nightly deep lane",
        description="Runs st check --deep (full gate without reuse, opted-in slow tests, and for repos with migrations or workspace packages the gate in a fresh clone with fresh deps and an empty CI database) once a day per project between 01:00 and 07:00 New York time.",
        cron="35 5-11 * * *",
        scope="system",
    ),
    ScheduleDefinition(
        schedule_id="runtime_hygiene",
        config_key="runtime_hygiene_enabled",
        label="Runtime hygiene audit",
        description="Runs the daily backup-aware audit for SummitFlow + Agent Hub host pressure, DB bloat, and runtime issues.",
        cron="10 16 * * *",
        scope="system",
        default_enabled=False,
    ),
)

_SCHEDULE_INDEX = {definition.schedule_id: definition for definition in SCHEDULE_DEFINITIONS}


def list_schedule_definitions() -> tuple[ScheduleDefinition, ...]:
    return SCHEDULE_DEFINITIONS


def get_schedule_definition(schedule_id: str) -> ScheduleDefinition:
    definition = _SCHEDULE_INDEX.get(schedule_id)
    if definition is None:
        raise KeyError(schedule_id)
    return definition


def schedule_cron(schedule_id: str) -> str:
    """The one cron literal for a schedule; scheduled.py registers it with Hatchet."""
    return get_schedule_definition(schedule_id).cron


def _control_project_id(
    project_id: str,
    definition: ScheduleDefinition,
) -> str:
    if definition.scope == "project":
        return project_id
    return SUMMITFLOW_CONTROL_PROJECT_ID


def is_schedule_enabled(project_id: str, schedule_id: str) -> bool:
    definition = get_schedule_definition(schedule_id)
    config = get_agent_config(_control_project_id(project_id, definition))
    return bool(config.get(definition.config_key, definition.default_enabled))
