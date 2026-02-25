"""backup_sources_overhaul

Replace project-centric backup system with source-based abstraction.
Creates backup_sources table, merges backup_schedules into it,
adds source_id to backups, drops backup_schedules.

Revision ID: 803e17ac7d9c
Revises: 52bde0e4709d
Create Date: 2026-02-25 11:16:31.628550

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "803e17ac7d9c"
down_revision: str | Sequence[str] | None = "52bde0e4709d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create backup_sources, migrate data, add source_id to backups, drop backup_schedules."""

    # 1. Fix pre-existing bugs: add missing verification columns to backups
    op.execute("ALTER TABLE backups ADD COLUMN IF NOT EXISTS verified BOOLEAN")
    op.execute("ALTER TABLE backups ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
    op.execute("ALTER TABLE backups ADD COLUMN IF NOT EXISTS checksum TEXT")
    op.execute("ALTER TABLE backups ADD COLUMN IF NOT EXISTS total_files INTEGER")
    op.execute("ALTER TABLE backups ADD COLUMN IF NOT EXISTS verification_json JSONB")

    # 2. Fix pre-existing bug: rename retention_count -> retention_days (idempotent)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'backup_schedules' AND column_name = 'retention_count'
            ) THEN
                ALTER TABLE backup_schedules RENAME COLUMN retention_count TO retention_days;
            END IF;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'backup_schedules'
            ) THEN
                ALTER TABLE backup_schedules ALTER COLUMN retention_days SET DEFAULT 14;
            END IF;
        END $$
    """)

    # 3. Create backup_sources table
    op.execute("""
        CREATE TABLE IF NOT EXISTS backup_sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'project',
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            frequency TEXT NOT NULL DEFAULT 'daily',
            retention_days INTEGER NOT NULL DEFAULT 14,
            last_run_at TIMESTAMPTZ,
            next_run_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT source_type_check CHECK (source_type IN ('project', 'config', 'workspace')),
            CONSTRAINT source_frequency_check CHECK (frequency IN ('daily', 'weekly', 'monthly'))
        )
    """)

    # 4. Seed project-type sources from existing projects
    op.execute("""
        INSERT INTO backup_sources (id, name, path, source_type, project_id)
        SELECT id, name, root_path, 'project', id
        FROM projects WHERE root_path IS NOT NULL
        ON CONFLICT (id) DO NOTHING
    """)

    # 5. Merge schedule data from backup_schedules into backup_sources
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'backup_schedules'
            ) THEN
                UPDATE backup_sources bs SET
                    enabled = s.enabled,
                    frequency = s.frequency,
                    retention_days = COALESCE(s.retention_days, 14),
                    last_run_at = s.last_run_at,
                    next_run_at = s.next_run_at
                FROM backup_schedules s WHERE bs.id = s.project_id;
            END IF;
        END $$
    """)

    # 6. Add non-project sources
    op.execute("""
        INSERT INTO backup_sources (id, name, path, source_type) VALUES
            ('.claude', 'Claude Config', '/home/kasadis/.claude', 'config'),
            ('persona-sandbox', 'Persona Sandbox', '/home/kasadis/persona-sandbox', 'workspace')
        ON CONFLICT (id) DO NOTHING
    """)

    # 7. Add source_id to backups, populate from project_id
    op.execute("ALTER TABLE backups ADD COLUMN IF NOT EXISTS source_id TEXT")
    op.execute("UPDATE backups SET source_id = project_id WHERE source_id IS NULL")
    op.execute("ALTER TABLE backups ALTER COLUMN source_id SET NOT NULL")

    # 8. Add FK to backup_sources (idempotent)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'backups_source_fk'
            ) THEN
                ALTER TABLE backups ADD CONSTRAINT backups_source_fk
                    FOREIGN KEY (source_id) REFERENCES backup_sources(id) ON DELETE CASCADE;
            END IF;
        END $$
    """)

    # 9. Drop old project_id FK
    op.execute("ALTER TABLE backups DROP CONSTRAINT IF EXISTS backups_project_id_fkey")

    # 10. Index on source_id
    op.execute("CREATE INDEX IF NOT EXISTS idx_backups_source ON backups(source_id)")

    # 11. Drop backup_schedules (merged into backup_sources)
    op.execute("DROP TABLE IF EXISTS backup_schedules")


def downgrade() -> None:
    """Reverse: recreate backup_schedules, remove source_id, drop backup_sources."""

    # Recreate backup_schedules from backup_sources data
    op.execute("""
        CREATE TABLE IF NOT EXISTS backup_schedules (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            frequency TEXT NOT NULL DEFAULT 'daily',
            last_run_at TIMESTAMPTZ,
            next_run_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            retention_days INTEGER NOT NULL DEFAULT 14,
            UNIQUE(project_id)
        )
    """)

    # Restore schedule data from backup_sources
    op.execute("""
        INSERT INTO backup_schedules (project_id, enabled, frequency, retention_days, last_run_at, next_run_at)
        SELECT id, enabled, frequency, retention_days, last_run_at, next_run_at
        FROM backup_sources
        WHERE source_type = 'project' AND project_id IS NOT NULL
        ON CONFLICT (project_id) DO NOTHING
    """)

    # Restore project_id FK on backups
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'backups_project_id_fkey'
            ) THEN
                ALTER TABLE backups ADD CONSTRAINT backups_project_id_fkey
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
            END IF;
        END $$
    """)

    # Drop source_id from backups
    op.execute("DROP INDEX IF EXISTS idx_backups_source")
    op.execute("ALTER TABLE backups DROP CONSTRAINT IF EXISTS backups_source_fk")
    op.execute("ALTER TABLE backups DROP COLUMN IF EXISTS source_id")

    # Drop backup_sources
    op.execute("DROP TABLE IF EXISTS backup_sources")
