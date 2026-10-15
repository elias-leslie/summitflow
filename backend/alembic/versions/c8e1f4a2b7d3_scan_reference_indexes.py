"""Index the scan-history reference columns retention cleanup probes.

cleanup_old_scan_history runs NOT EXISTS against these five columns for every
candidate row; without indexes each probe scans the referencing table.

Revision ID: c8e1f4a2b7d3
Revises: aa7b8a7f0c76
"""

from alembic import op

revision = "c8e1f4a2b7d3"
down_revision = "aa7b8a7f0c76"
branch_labels = None
depends_on = None

_INDEXES = (
    ("idx_scan_history_previous_scan", "scan_history", "previous_scan_id"),
    ("idx_qa_issues_detected_in_scan", "qa_issues", "detected_in_scan_id"),
    ("idx_qa_issues_resolution_scan", "qa_issues", "resolution_scan_id"),
    ("idx_refactor_sessions_baseline_scan", "refactor_sessions", "baseline_scan_id"),
    ("idx_refactor_sessions_final_scan", "refactor_sessions", "final_scan_id"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, column in _INDEXES:
            op.create_index(name, table, [column], postgresql_where=f"{column} IS NOT NULL",
                            postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, _column in _INDEXES:
            op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)
