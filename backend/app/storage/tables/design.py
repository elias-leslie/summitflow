"""Design-related tables: standards, rules, and generated assets."""

import psycopg


def create_design_tables(cur: psycopg.Cursor) -> None:
    """Create design tables and their indexes."""
    _create_design_standards_table(cur)
    _create_design_rules_table(cur)
    _create_design_assets_table(cur)
    _create_design_asset_exports_table(cur)


def _create_design_standards_table(cur: psycopg.Cursor) -> None:
    """Create design_standards table and indexes.

    Design standards support UI/UX standards with inheritance.
    """
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS design_standards (
            id SERIAL PRIMARY KEY,
            project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            base_standard_id INTEGER REFERENCES design_standards(id) ON DELETE SET NULL,
            is_base BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(project_id, name)
        )
        """
    )

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_standards_project ON design_standards(project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_standards_base ON design_standards(is_base) "
        "WHERE is_base = TRUE"
    )


def _create_design_rules_table(cur: psycopg.Cursor) -> None:
    """Create design_rules table and indexes.

    Design rules are individual rules within a design standard.
    """
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS design_rules (
            id SERIAL PRIMARY KEY,
            standard_id INTEGER NOT NULL REFERENCES design_standards(id) ON DELETE CASCADE,
            category VARCHAR(50) NOT NULL,
            rule_id VARCHAR(50) NOT NULL,
            name VARCHAR(200) NOT NULL,
            requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(standard_id, rule_id)
        )
        """
    )

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_design_rules_standard ON design_rules(standard_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_design_rules_category ON design_rules(category)")


def _create_design_assets_table(cur: psycopg.Cursor) -> None:
    """Create design_assets table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS design_assets (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            asset_id VARCHAR(50) NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            asset_type VARCHAR(50) NOT NULL,
            workflow VARCHAR(50) NOT NULL DEFAULT 'concept',
            status VARCHAR(30) NOT NULL DEFAULT 'generated',
            prompt TEXT NOT NULL,
            negative_prompt TEXT,
            style_prompt TEXT,
            background VARCHAR(20) NOT NULL DEFAULT 'transparent',
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            transparent_background BOOLEAN NOT NULL DEFAULT FALSE,
            model VARCHAR(100),
            generator VARCHAR(100),
            file_path TEXT,
            source_asset_id INTEGER REFERENCES design_assets(id) ON DELETE SET NULL,
            sheet_columns INTEGER,
            sheet_rows INTEGER,
            frame_width INTEGER,
            frame_height INTEGER,
            animation_labels TEXT[] NOT NULL DEFAULT '{}',
            tags TEXT[] NOT NULL DEFAULT '{}',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            approved_at TIMESTAMPTZ,
            approved_by VARCHAR(100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_design_assets_project_asset UNIQUE(project_id, asset_id),
            CONSTRAINT ck_design_assets_type CHECK (
                asset_type IN (
                    'sprite',
                    'sprite_sheet',
                    'portrait',
                    'environment',
                    'icon',
                    'illustration',
                    'ui_texture',
                    'marketing_mockup',
                    'tile_set',
                    'concept_art'
                )
            ),
            CONSTRAINT ck_design_assets_workflow CHECK (
                workflow IN ('concept', 'production', 'marketing', 'ui')
            ),
            CONSTRAINT ck_design_assets_status CHECK (
                status IN ('generated', 'approved', 'rejected', 'archived', 'exported')
            ),
            CONSTRAINT ck_design_assets_background CHECK (
                background IN ('transparent', 'solid', 'scene')
            )
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_assets_project ON design_assets(project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_assets_type ON design_assets(project_id, asset_type)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_assets_status ON design_assets(project_id, status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_assets_source ON design_assets(source_asset_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_assets_created ON design_assets(project_id, created_at DESC)"
    )


def _create_design_asset_exports_table(cur: psycopg.Cursor) -> None:
    """Create design_asset_exports table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS design_asset_exports (
            id SERIAL PRIMARY KEY,
            asset_id INTEGER NOT NULL REFERENCES design_assets(id) ON DELETE CASCADE,
            export_id VARCHAR(50) NOT NULL,
            export_type VARCHAR(30) NOT NULL,
            file_path TEXT NOT NULL,
            manifest_path TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_design_asset_exports UNIQUE(asset_id, export_id),
            CONSTRAINT ck_design_asset_exports_type CHECK (
                export_type IN ('original', 'sprite_frames', 'atlas_json')
            )
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_asset_exports_asset ON design_asset_exports(asset_id)"
    )
