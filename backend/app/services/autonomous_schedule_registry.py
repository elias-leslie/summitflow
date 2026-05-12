"""Registry of SummitFlow scheduled workflows and their UI-manageable controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from app.storage.agent_configs import AgentConfig, get_agent_config, update_agent_config

ScheduleScope = Literal["project", "system"]
SUMMITFLOW_CONTROL_PROJECT_ID = "summitflow"


@dataclass(frozen=True)
class AutonomousScheduleDefinition:
    """Config-backed schedule metadata exposed to the UI."""

    schedule_id: str
    config_key: str
    label: str
    description: str
    cron: str
    scope: ScheduleScope
    default_enabled: bool = True


class AutonomousScheduleState(TypedDict):
    schedule_id: str
    config_key: str
    label: str
    description: str
    cron: str
    scope: ScheduleScope
    default_enabled: bool
    enabled: bool
    managed_project_id: str


SCHEDULE_DEFINITIONS: tuple[AutonomousScheduleDefinition, ...] = (
    AutonomousScheduleDefinition(
        schedule_id="work_pickup",
        config_key="work_pickup_enabled",
        label="Autonomous work pickup",
        description="Dispatches pending autonomous tasks into triage, planning, or execution when the project check frequency is due.",
        cron="*/15 * * * *",
        scope="project",
        default_enabled=False,
    ),
    AutonomousScheduleDefinition(
        schedule_id="task_generation",
        config_key="task_generation_enabled",
        label="Routine upkeep trigger",
        description="Discovers refactor, quality, and feedback tasks without dispatching execution.",
        cron="0 * * * *",
        scope="project",
    ),
    AutonomousScheduleDefinition(
        schedule_id="reset_claims",
        config_key="reset_claims_enabled",
        label="Claim reset",
        description="Clears expired task claims so stuck work can be retried intentionally.",
        cron="*/15 * * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="scan_projects",
        config_key="scan_projects_enabled",
        label="Project scan",
        description="Refreshes explorer scans across projects.",
        cron="0 */6 * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="refresh_precision_indexes",
        config_key="refresh_precision_indexes_enabled",
        label="Precision index refresh",
        description="Rebuilds precision search indexes for symbol-first context retrieval.",
        cron="10 */2 * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="refresh_graphify_graphs",
        config_key="refresh_graphify_graphs_enabled",
        label="Graphify graph refresh",
        description="Refreshes stale existing Graphify code graphs for topology retrieval.",
        cron="25 */2 * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="scheduled_backups",
        config_key="scheduled_backups_enabled",
        label="Scheduled backups",
        description="Creates backup snapshots on the configured cadence.",
        cron="30 * * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="stale_cleanup",
        config_key="stale_cleanup_enabled",
        label="Stale cleanup",
        description="Runs daily maintenance and stale cleanup tasks.",
        cron="0 4 * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="self_healing",
        config_key="self_healing_enabled",
        label="Self-healing",
        description="Checks repeated failures and runs the self-healing orchestrator.",
        cron="*/30 * * * *",
        scope="system",
        default_enabled=False,
    ),
    AutonomousScheduleDefinition(
        schedule_id="prod_smoke_test",
        config_key="prod_smoke_test_enabled",
        label="Production smoke test",
        description="Runs the lightweight production smoke suite and only notifies on state changes.",
        cron="*/30 * * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="health_monitor",
        config_key="health_monitor_enabled",
        label="Health monitor",
        description="Performs frequent health checks and notifications.",
        cron="*/5 * * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="pending_drain",
        config_key="pending_drain_enabled",
        label="Pending backup drain",
        description="Drains pending backup work that could not complete inline.",
        cron="*/30 * * * *",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="restore_tests",
        config_key="restore_tests_enabled",
        label="Restore verification",
        description="Runs weekly restore tests against backup artifacts.",
        cron="0 6 * * 0",
        scope="system",
    ),
    AutonomousScheduleDefinition(
        schedule_id="runtime_hygiene",
        config_key="runtime_hygiene_enabled",
        label="Runtime hygiene audit",
        description="Runs the daily backup-aware audit for SummitFlow + Agent Hub host pressure, DB bloat, and runtime issues.",
        cron="10 16 * * *",
        scope="system",
        default_enabled=False,
    ),
    AutonomousScheduleDefinition(
        schedule_id="tool_governance",
        config_key="tool_governance_enabled",
        label="Tool governance scan",
        description="Runs the daily st tool adoption, missed-tool, and context-cost scan and emits deduped feedback for actionable findings.",
        cron="40 16 * * *",
        scope="system",
    ),
)

_SCHEDULE_INDEX = {definition.schedule_id: definition for definition in SCHEDULE_DEFINITIONS}


def list_autonomous_schedule_definitions() -> tuple[AutonomousScheduleDefinition, ...]:
    return SCHEDULE_DEFINITIONS


def get_autonomous_schedule_definition(schedule_id: str) -> AutonomousScheduleDefinition:
    definition = _SCHEDULE_INDEX.get(schedule_id)
    if definition is None:
        raise KeyError(schedule_id)
    return definition


def _control_project_id(
    project_id: str,
    definition: AutonomousScheduleDefinition,
) -> str:
    if definition.scope == "project":
        return project_id
    return SUMMITFLOW_CONTROL_PROJECT_ID


def is_schedule_enabled(project_id: str, schedule_id: str) -> bool:
    definition = get_autonomous_schedule_definition(schedule_id)
    config = get_agent_config(_control_project_id(project_id, definition))
    return bool(config.get(definition.config_key, definition.default_enabled))


def describe_autonomous_schedule(project_id: str, schedule_id: str) -> AutonomousScheduleState:
    definition = get_autonomous_schedule_definition(schedule_id)
    managed_project_id = _control_project_id(project_id, definition)
    config = get_agent_config(managed_project_id)
    return {
        "schedule_id": definition.schedule_id,
        "config_key": definition.config_key,
        "label": definition.label,
        "description": definition.description,
        "cron": definition.cron,
        "scope": definition.scope,
        "default_enabled": definition.default_enabled,
        "enabled": bool(config.get(definition.config_key, definition.default_enabled)),
        "managed_project_id": managed_project_id,
    }


def list_autonomous_schedule_states(project_id: str) -> list[AutonomousScheduleState]:
    project_config = get_agent_config(project_id)
    system_config = (
        project_config
        if project_id == SUMMITFLOW_CONTROL_PROJECT_ID
        else get_agent_config(SUMMITFLOW_CONTROL_PROJECT_ID)
    )
    states: list[AutonomousScheduleState] = []
    for definition in SCHEDULE_DEFINITIONS:
        managed_project_id = _control_project_id(project_id, definition)
        config = project_config if managed_project_id == project_id else system_config
        states.append(
            {
                "schedule_id": definition.schedule_id,
                "config_key": definition.config_key,
                "label": definition.label,
                "description": definition.description,
                "cron": definition.cron,
                "scope": definition.scope,
                "default_enabled": definition.default_enabled,
                "enabled": bool(config.get(definition.config_key, definition.default_enabled)),
                "managed_project_id": managed_project_id,
            }
        )
    return states


def set_autonomous_schedule_enabled(
    project_id: str,
    schedule_id: str,
    *,
    enabled: bool,
) -> AutonomousScheduleState:
    definition = get_autonomous_schedule_definition(schedule_id)
    managed_project_id = _control_project_id(project_id, definition)
    update_agent_config(
        managed_project_id,
        cast(AgentConfig, {definition.config_key: enabled}),
    )
    return describe_autonomous_schedule(project_id, schedule_id)
