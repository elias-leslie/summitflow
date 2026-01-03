-- Migration: 047_drop_deprecated_columns.sql
-- Description: Drop deprecated columns and tables from TDD/Spec cleanup

-- Drop deprecated columns from capabilities table
-- These were marked as deprecated in previous phases

-- Drop locked_at column (capability locking feature removed in Phase 1)
ALTER TABLE capabilities DROP COLUMN IF EXISTS locked_at;

-- Drop verification_url column (dead column, never used)
ALTER TABLE capabilities DROP COLUMN IF EXISTS verification_url;

-- Drop sitemap_entries table (0 records, dead feature)
DROP TABLE IF EXISTS sitemap_entries CASCADE;

-- Remove any references in schema comments
COMMENT ON TABLE capabilities IS 'Product capabilities with test linkage - cleaned in TDD spec review';
