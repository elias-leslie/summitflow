"""Drop the Explorer tables and the retired scan schedule flags.

Revision ID: cc52f6de0338
Revises: b4e8c2d7a913

Explorer is deleted: its UI is gone and `st search` no longer reads a hosted symbol index. The only
surviving output, `.index.yaml`, is now generated live from the project registration and checkout.
explorer_entries and explorer_symbols held derived scan output, reproducible from the checkouts.
qa_issues (11,746 Explorer-detected issues, last created 2026-09-23), scan_history and scan_states
were exported as JSONL to /srv/workspaces/archive/summitflow-explorer-2026-10-27/ before this
migration; nothing reads any of these tables.

The two retired schedule flags are stripped from projects.agent_configs; every stored value equalled
the code default (true), so the strip loses nothing.
"""

from alembic import op

revision = "cc52f6de0338"
down_revision = "b4e8c2d7a913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # qa_issues references explorer_entries; scan_history references itself.
    op.execute("DROP TABLE IF EXISTS qa_issues")
    op.execute("DROP TABLE IF EXISTS explorer_symbols")
    op.execute("DROP TABLE IF EXISTS explorer_entries")
    op.execute("DROP TABLE IF EXISTS scan_history")
    op.execute("DROP TABLE IF EXISTS scan_states")
    op.execute(
        """
        UPDATE projects
        SET agent_configs = agent_configs - 'scan_projects_enabled' - 'refresh_precision_indexes_enabled'
        WHERE agent_configs ?| ARRAY['scan_projects_enabled', 'refresh_precision_indexes_enabled']
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Cannot restore the Explorer tables: the code that wrote them is deleted. qa_issues and scan history "
        "are in /srv/workspaces/archive/summitflow-explorer-2026-10-27/; restore anything else from a database "
        "backup taken before this revision."
    )
