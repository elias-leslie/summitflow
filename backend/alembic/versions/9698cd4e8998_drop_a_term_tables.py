"""Drop A-Term's tables now that A-Term keeps no state in Postgres.

A-Term moved its view state to local SQLite and its sessions to Tether, and no
longer connects to this database. Dropped: every a_term_* table (including
a_term_alembic_version) and agent_tools. Owner approved 2026-10-11. Schema and
rows were archived first with pg_dump (custom and plain SQL) to
/srv/workspaces/backups/a-term-postgres-2026-10-11/; that dump was restored
into a scratch database and its row counts matched the live tables.

Downgrade does nothing: restore the tables from that dump with pg_restore if
they are ever needed again.

Revision ID: 9698cd4e8998
Revises: a7e3c5d91b42
"""

from alembic import op

revision = "9698cd4e8998"
down_revision = "a7e3c5d91b42"
branch_labels = None
depends_on = None

# Children before parents so no CASCADE is needed.
_TABLES = (
    "a_term_note_versions",
    "a_term_notes",
    "a_term_session_recordings",
    "a_term_sessions",
    "a_term_panes",
    "a_term_project_settings",
    "a_term_root_requests",
    "a_term_maintenance_runs",
    "a_term_alembic_version",
    "agent_tools",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    """No-op; restore from the pg_dump archive named in the module docstring."""
