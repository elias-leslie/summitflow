"""reconcile_orphaned_sql_migrations_101_105

Reconciles 5 raw SQL migrations (101-105) that were applied directly
to the database after the Alembic baseline but never tracked by Alembic.

Source files archived in migrations-archive/:
  101_add_agent_override.sql       - ADD COLUMN tasks.agent_override
  102_add_all_missing_constraints  - ADD PRIMARY KEYs (26 tables), UNIQUE (7)
  103_add_foreign_keys.sql         - ADD FOREIGN KEYs (31), orphan cleanup
  104_drop_ideas.sql               - DROP ideas table, notifications.idea_id
  105_add_ai_review_flag.sql       - ADD COLUMN tasks.ai_review

All operations are idempotent. On an existing DB these are no-ops.

Revision ID: 56459b1bf358
Revises: 803e17ac7d9c
Create Date: 2026-02-25 11:27:05.197321

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "56459b1bf358"
down_revision: str | Sequence[str] | None = "803e17ac7d9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _safe_delete(table: str, where: str) -> str:
    """Generate DELETE that skips if table doesn't exist."""
    return f"""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{table}' AND table_schema = 'public'
            ) THEN
                DELETE FROM {table} WHERE {where};
            END IF;
        END $$
    """


def _add_pk_if_missing(table: str, columns: str = "id") -> str:
    """Generate idempotent ADD PRIMARY KEY."""
    return f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = '{table}' AND constraint_type = 'PRIMARY KEY'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{table}' AND table_schema = 'public'
            ) THEN
                ALTER TABLE {table} ADD PRIMARY KEY ({columns});
            END IF;
        END $$
    """


def _add_unique_if_missing(table: str, constraint: str, columns: str) -> str:
    """Generate idempotent ADD UNIQUE constraint."""
    return f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = '{constraint}'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{table}' AND table_schema = 'public'
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {constraint} UNIQUE ({columns});
            END IF;
        END $$
    """


def _add_fk_if_missing(table: str, constraint: str, column: str,
                        ref_table: str, ref_col: str = "id",
                        on_delete: str = "CASCADE") -> str:
    """Generate idempotent ADD FOREIGN KEY."""
    return f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = '{constraint}'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{table}' AND table_schema = 'public'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{ref_table}' AND table_schema = 'public'
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {constraint}
                    FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_col})
                    ON DELETE {on_delete};
            END IF;
        END $$
    """


def upgrade() -> None:
    """Reconcile orphaned SQL migrations 101-105 into Alembic tracking."""

    # =========================================================================
    # 101: ADD COLUMN tasks.agent_override
    # =========================================================================
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS agent_override VARCHAR(50)")

    # =========================================================================
    # 102: ADD PRIMARY KEYs and UNIQUE constraints
    # Dedup steps skipped — already executed, no-op on clean DB.
    # Tables that may have been dropped by later migrations (ideas,
    # backup_schedules, celery_taskmeta) are guarded by IF EXISTS.
    # =========================================================================

    # Primary keys — serial/int id
    for table in [
        "agent_sessions", "explorer_entries", "migration_backup",
        "mockups", "qa_issues", "quality_check_results", "scan_history",
        "subtask_dependencies", "subtask_summaries", "task_dependencies",
        "task_subtask_steps",
    ]:
        op.execute(_add_pk_if_missing(table))

    # Primary keys — text/varchar id
    for table in ["backups", "task_subtasks"]:
        op.execute(_add_pk_if_missing(table))

    # Primary keys — UUID id
    for table in [
        "events", "subtask_citations", "terminal_panes",
        "terminal_sessions", "user_prompts",
    ]:
        op.execute(_add_pk_if_missing(table))

    # Primary keys — natural keys
    op.execute(_add_pk_if_missing("scan_states", "project_id"))
    op.execute(_add_pk_if_missing("terminal_project_settings", "project_id"))
    op.execute(_add_pk_if_missing("task_labels", "task_id, label"))
    op.execute(_add_pk_if_missing("alembic_version", "version_num"))

    # Unique constraints
    op.execute(_add_unique_if_missing(
        "explorer_entries", "explorer_entries_project_entry_path_key",
        "project_id, entry_type, path"))
    op.execute(_add_unique_if_missing(
        "subtask_dependencies", "subtask_dependencies_subtask_depends_key",
        "subtask_id, depends_on_subtask_id"))
    op.execute(_add_unique_if_missing(
        "subtask_summaries", "subtask_summaries_subtask_id_key", "subtask_id"))
    op.execute(_add_unique_if_missing(
        "task_dependencies", "task_dependencies_task_depends_type_key",
        "task_id, depends_on_task_id, dependency_type"))
    op.execute(_add_unique_if_missing(
        "task_subtask_steps", "task_subtask_steps_subtask_step_key",
        "subtask_id, step_number"))

    # =========================================================================
    # 103: ADD FOREIGN KEYs
    # Orphan cleanup required before FK creation to prevent violations.
    # =========================================================================

    # Subtask-level orphans
    op.execute(_safe_delete("task_subtask_steps", "subtask_id NOT IN (SELECT id FROM task_subtasks)"))
    op.execute(_safe_delete("subtask_dependencies", "subtask_id NOT IN (SELECT id FROM task_subtasks)"))
    op.execute(_safe_delete("subtask_dependencies", "depends_on_subtask_id NOT IN (SELECT id FROM task_subtasks)"))
    op.execute(_safe_delete("subtask_summaries", "subtask_id NOT IN (SELECT id FROM task_subtasks)"))
    op.execute(_safe_delete("subtask_citations", "subtask_id NOT IN (SELECT id FROM task_subtasks)"))

    # Task-level orphans
    op.execute(_safe_delete("task_subtasks", "task_id NOT IN (SELECT id FROM tasks)"))
    op.execute(_safe_delete("task_spirit", "task_id NOT IN (SELECT id FROM tasks)"))
    op.execute(_safe_delete("task_labels", "task_id NOT IN (SELECT id FROM tasks)"))
    op.execute(_safe_delete("task_dependencies", "task_id NOT IN (SELECT id FROM tasks)"))
    op.execute(_safe_delete("task_dependencies", "depends_on_task_id NOT IN (SELECT id FROM tasks)"))
    op.execute(_safe_delete("mockups", "task_id IS NOT NULL AND task_id NOT IN (SELECT id FROM tasks)"))
    op.execute(_safe_delete("quality_check_results",
                            "escalation_task_id IS NOT NULL AND escalation_task_id NOT IN (SELECT id FROM tasks)"))

    # Project-level orphans (tables may have been dropped by later migrations)
    for table in [
        "events", "mockups", "backups", "explorer_entries", "qa_issues",
        "quality_check_results", "scan_history", "scan_states",
        "refactor_sessions", "user_prompts", "agent_sessions",
        "notifications", "project_agent_config", "sitemap_entries",
        "code_health_lists",
    ]:
        op.execute(_safe_delete(table, "project_id NOT IN (SELECT id FROM projects)"))

    # Explorer-level orphans
    op.execute(_safe_delete("explorer_sub_elements", "explorer_entry_id NOT IN (SELECT id FROM explorer_entries)"))
    op.execute(_safe_delete("qa_issues", "entry_id IS NOT NULL AND entry_id NOT IN (SELECT id FROM explorer_entries)"))

    # Task hierarchy
    op.execute(_add_fk_if_missing("task_subtasks", "task_subtasks_task_id_fkey",
                                   "task_id", "tasks"))
    op.execute(_add_fk_if_missing("task_subtask_steps", "task_subtask_steps_subtask_id_fkey",
                                   "subtask_id", "task_subtasks"))
    op.execute(_add_fk_if_missing("task_spirit", "task_spirit_task_id_fkey",
                                   "task_id", "tasks"))
    op.execute(_add_fk_if_missing("task_labels", "task_labels_task_id_fkey",
                                   "task_id", "tasks"))
    op.execute(_add_fk_if_missing("task_dependencies", "task_dependencies_task_id_fkey",
                                   "task_id", "tasks"))
    op.execute(_add_fk_if_missing("task_dependencies", "task_dependencies_depends_on_task_id_fkey",
                                   "depends_on_task_id", "tasks"))

    # Subtask hierarchy
    op.execute(_add_fk_if_missing("subtask_dependencies", "subtask_dependencies_subtask_id_fkey",
                                   "subtask_id", "task_subtasks"))
    op.execute(_add_fk_if_missing("subtask_dependencies", "subtask_dependencies_depends_on_subtask_id_fkey",
                                   "depends_on_subtask_id", "task_subtasks"))
    op.execute(_add_fk_if_missing("subtask_summaries", "subtask_summaries_subtask_id_fkey",
                                   "subtask_id", "task_subtasks"))
    op.execute(_add_fk_if_missing("subtask_citations", "subtask_citations_subtask_id_fkey",
                                   "subtask_id", "task_subtasks"))

    # Project references
    op.execute(_add_fk_if_missing("tasks", "tasks_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("tasks", "tasks_parent_task_id_fkey",
                                   "parent_task_id", "tasks", on_delete="SET NULL"))
    op.execute(_add_fk_if_missing("events", "events_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("mockups", "mockups_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("mockups", "mockups_task_id_fkey",
                                   "task_id", "tasks", on_delete="SET NULL"))
    op.execute(_add_fk_if_missing("explorer_entries", "explorer_entries_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("explorer_sub_elements", "explorer_sub_elements_explorer_entry_id_fkey",
                                   "explorer_entry_id", "explorer_entries"))
    op.execute(_add_fk_if_missing("qa_issues", "qa_issues_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("qa_issues", "qa_issues_entry_id_fkey",
                                   "entry_id", "explorer_entries", on_delete="SET NULL"))
    op.execute(_add_fk_if_missing("quality_check_results", "quality_check_results_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("quality_check_results", "quality_check_results_escalation_task_id_fkey",
                                   "escalation_task_id", "tasks", on_delete="SET NULL"))
    op.execute(_add_fk_if_missing("scan_history", "scan_history_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("scan_states", "scan_states_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("refactor_sessions", "refactor_sessions_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("user_prompts", "user_prompts_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("agent_sessions", "agent_sessions_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("notifications", "notifications_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("project_agent_config", "project_agent_config_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("sitemap_entries", "sitemap_entries_project_id_fkey",
                                   "project_id", "projects"))
    op.execute(_add_fk_if_missing("code_health_lists", "code_health_lists_project_id_fkey",
                                   "project_id", "projects"))

    # =========================================================================
    # 104: DROP ideas table
    # Also cleans up idx_notification_idea from Alembic migration a14ee32465a1
    # which added idea_id on Feb 14, one day before 104 dropped it.
    # =========================================================================
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'ideas' AND table_schema = 'public') THEN
                ALTER TABLE ideas DROP CONSTRAINT IF EXISTS ideas_project_id_fkey;
                ALTER TABLE ideas DROP CONSTRAINT IF EXISTS ideas_task_id_fkey;
                DROP TABLE ideas;
            END IF;
        END $$
    """)
    op.execute("DROP INDEX IF EXISTS idx_notification_idea")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS idea_id")

    # =========================================================================
    # 105: ADD COLUMN tasks.ai_review
    # =========================================================================
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ai_review BOOLEAN NOT NULL DEFAULT TRUE"
    )


def downgrade() -> None:
    """Reverse reconciliation — best-effort, not all steps are reversible."""

    # 105: drop ai_review
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS ai_review")

    # 104: recreate ideas table (structure only, data is gone)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT,
            source TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS idea_id TEXT")

    # 103: drop FKs (reverse of additions)
    fks = [
        ("code_health_lists", "code_health_lists_project_id_fkey"),
        ("sitemap_entries", "sitemap_entries_project_id_fkey"),
        ("project_agent_config", "project_agent_config_project_id_fkey"),
        ("notifications", "notifications_project_id_fkey"),
        ("agent_sessions", "agent_sessions_project_id_fkey"),
        ("user_prompts", "user_prompts_project_id_fkey"),
        ("refactor_sessions", "refactor_sessions_project_id_fkey"),
        ("scan_states", "scan_states_project_id_fkey"),
        ("scan_history", "scan_history_project_id_fkey"),
        ("quality_check_results", "quality_check_results_escalation_task_id_fkey"),
        ("quality_check_results", "quality_check_results_project_id_fkey"),
        ("qa_issues", "qa_issues_entry_id_fkey"),
        ("qa_issues", "qa_issues_project_id_fkey"),
        ("explorer_sub_elements", "explorer_sub_elements_explorer_entry_id_fkey"),
        ("explorer_entries", "explorer_entries_project_id_fkey"),
        ("mockups", "mockups_task_id_fkey"),
        ("mockups", "mockups_project_id_fkey"),
        ("events", "events_project_id_fkey"),
        ("tasks", "tasks_parent_task_id_fkey"),
        ("tasks", "tasks_project_id_fkey"),
        ("subtask_citations", "subtask_citations_subtask_id_fkey"),
        ("subtask_summaries", "subtask_summaries_subtask_id_fkey"),
        ("subtask_dependencies", "subtask_dependencies_depends_on_subtask_id_fkey"),
        ("subtask_dependencies", "subtask_dependencies_subtask_id_fkey"),
        ("task_dependencies", "task_dependencies_depends_on_task_id_fkey"),
        ("task_dependencies", "task_dependencies_task_id_fkey"),
        ("task_labels", "task_labels_task_id_fkey"),
        ("task_spirit", "task_spirit_task_id_fkey"),
        ("task_subtask_steps", "task_subtask_steps_subtask_id_fkey"),
        ("task_subtasks", "task_subtasks_task_id_fkey"),
    ]
    for table, constraint in fks:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")

    # 102: drop unique constraints (PKs are not reversed — too destructive)
    op.execute("ALTER TABLE task_subtask_steps DROP CONSTRAINT IF EXISTS task_subtask_steps_subtask_step_key")
    op.execute("ALTER TABLE task_dependencies DROP CONSTRAINT IF EXISTS task_dependencies_task_depends_type_key")
    op.execute("ALTER TABLE subtask_summaries DROP CONSTRAINT IF EXISTS subtask_summaries_subtask_id_key")
    op.execute("ALTER TABLE subtask_dependencies DROP CONSTRAINT IF EXISTS subtask_dependencies_subtask_depends_key")
    op.execute("ALTER TABLE explorer_entries DROP CONSTRAINT IF EXISTS explorer_entries_project_entry_path_key")

    # 101: drop agent_override
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS agent_override")
