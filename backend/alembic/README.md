# Alembic Migrations for SummitFlow

## Overview

SummitFlow uses Alembic for database migrations going forward. The original schema was created by 100 raw SQL migrations in `migrations/*.sql`.

## Quick Reference

```bash
# Check current version
DATABASE_URL="$DATABASE_URL" alembic current

# Apply all pending migrations
DATABASE_URL="$DATABASE_URL" alembic upgrade head

# Create a new migration
DATABASE_URL="$DATABASE_URL" alembic revision -m "description_of_change"

# Downgrade one version
DATABASE_URL="$DATABASE_URL" alembic downgrade -1

# Show migration history
DATABASE_URL="$DATABASE_URL" alembic history
```

## Setup for New Databases

For a fresh database:

1. Run the legacy SQL migrations first:
   ```bash
   python migrations/run_migration.py
   ```

2. Stamp Alembic baseline:
   ```bash
   DATABASE_URL="$DATABASE_URL" alembic stamp head
   ```

## Creating New Migrations

Since SummitFlow uses raw psycopg (not SQLAlchemy models), migrations are written manually:

```bash
# Create empty migration
DATABASE_URL="$DATABASE_URL" alembic revision -m "add_new_column_to_tasks"
```

Then edit the generated file in `alembic/versions/` to add your SQL:

```python
from alembic import op

def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN new_col TEXT")

def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN new_col")
```

## Notes

- No autogenerate support (no SQLAlchemy models)
- All migrations should be idempotent where possible
- Test migrations locally before deploying
- The baseline migration cannot be downgraded
