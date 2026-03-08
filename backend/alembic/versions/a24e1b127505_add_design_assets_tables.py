"""add design assets tables

Revision ID: a24e1b127505
Revises: d1cd35b5b946
Create Date: 2026-03-07 22:42:47.862486

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a24e1b127505'
down_revision: str | Sequence[str] | None = 'd1cd35b5b946'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "design_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("workflow", sa.String(length=50), nullable=False, server_default="concept"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="generated"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("style_prompt", sa.Text(), nullable=True),
        sa.Column("background", sa.String(length=20), nullable=False, server_default="transparent"),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("transparent_background", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("generator", sa.String(length=100), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("source_asset_id", sa.Integer(), sa.ForeignKey("design_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sheet_columns", sa.Integer(), nullable=True),
        sa.Column("sheet_rows", sa.Integer(), nullable=True),
        sa.Column("frame_width", sa.Integer(), nullable=True),
        sa.Column("frame_height", sa.Integer(), nullable=True),
        sa.Column(
            "animation_labels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "asset_id", name="uq_design_assets_project_asset"),
    )
    op.create_check_constraint(
        "ck_design_assets_type",
        "design_assets",
        "asset_type IN ('sprite', 'sprite_sheet', 'portrait', 'environment', 'icon', 'illustration', 'ui_texture', 'marketing_mockup', 'tile_set', 'concept_art')",
    )
    op.create_check_constraint(
        "ck_design_assets_workflow",
        "design_assets",
        "workflow IN ('concept', 'production', 'marketing', 'ui')",
    )
    op.create_check_constraint(
        "ck_design_assets_status",
        "design_assets",
        "status IN ('generated', 'approved', 'rejected', 'archived', 'exported')",
    )
    op.create_check_constraint(
        "ck_design_assets_background",
        "design_assets",
        "background IN ('transparent', 'solid', 'scene')",
    )
    op.create_index("idx_design_assets_project", "design_assets", ["project_id"])
    op.create_index("idx_design_assets_type", "design_assets", ["project_id", "asset_type"])
    op.create_index("idx_design_assets_status", "design_assets", ["project_id", "status"])
    op.create_index("idx_design_assets_source", "design_assets", ["source_asset_id"])
    op.create_index("idx_design_assets_created", "design_assets", ["project_id", "created_at"])

    op.create_table(
        "design_asset_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("design_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("export_id", sa.String(length=50), nullable=False),
        sa.Column("export_type", sa.String(length=30), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("manifest_path", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("asset_id", "export_id", name="uq_design_asset_exports"),
    )
    op.create_check_constraint(
        "ck_design_asset_exports_type",
        "design_asset_exports",
        "export_type IN ('original', 'sprite_frames', 'atlas_json')",
    )
    op.create_index("idx_design_asset_exports_asset", "design_asset_exports", ["asset_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_design_asset_exports_asset", table_name="design_asset_exports")
    op.drop_constraint("ck_design_asset_exports_type", "design_asset_exports", type_="check")
    op.drop_table("design_asset_exports")
    op.drop_index("idx_design_assets_created", table_name="design_assets")
    op.drop_index("idx_design_assets_source", table_name="design_assets")
    op.drop_index("idx_design_assets_status", table_name="design_assets")
    op.drop_index("idx_design_assets_type", table_name="design_assets")
    op.drop_index("idx_design_assets_project", table_name="design_assets")
    op.drop_constraint("ck_design_assets_background", "design_assets", type_="check")
    op.drop_constraint("ck_design_assets_status", "design_assets", type_="check")
    op.drop_constraint("ck_design_assets_workflow", "design_assets", type_="check")
    op.drop_constraint("ck_design_assets_type", "design_assets", type_="check")
    op.drop_table("design_assets")
