"""Drop the design standards tables.

Revision ID: 70b219cea955
Revises: cc52f6de0338

The design standards feature is deleted (owner decision 2026-10-27): its API, storage and UI panel are gone and
design-tools no longer reads standards for analyze-page. Per-project design guidance lives in agent-hub
project-scoped prompts instead. On 2026-10-27 both tables had 0 rows and pg_stat_user_tables recorded 0 inserts
(n_tup_ins = 0), so there is nothing to archive. The only foreign keys touching them are internal
(design_rules.standard_id -> design_standards, design_standards.base_standard_id -> design_standards) plus
design_standards.project_id -> projects; nothing else (mockups included) references either table.
"""

from alembic import op

revision = "70b219cea955"
down_revision = "cc52f6de0338"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # design_rules references design_standards.
    op.execute("DROP TABLE IF EXISTS design_rules")
    op.execute("DROP TABLE IF EXISTS design_standards")


def downgrade() -> None:
    raise RuntimeError(
        "Cannot restore the design standards tables: the code that used them is deleted and they held no rows."
    )
