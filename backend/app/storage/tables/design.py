"""Design standards tables: design_standards, design_rules."""

import psycopg


def create_design_tables(cur: psycopg.Cursor) -> None:
    """Create design standards tables and their indexes."""
    _create_design_standards_table(cur)
    _create_design_rules_table(cur)


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
