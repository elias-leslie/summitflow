-- Migration 026: Tech Debt Cleanup
-- Date: 2025-12-25
-- Purpose: Remove deprecated tables and columns identified in tech debt review
--
-- REMOVED:
-- - prompts.verification_* columns (dead code - no backend logic)
-- - file_audit table (superseded by explorer_entries)
-- - scanner_database table (superseded by explorer_entries)
-- - scanner_api table (superseded by explorer_entries)
-- - scanner_celery table (superseded by explorer_entries)
-- - sitemap_health_history table (incomplete feature, no producers)
--
-- Run with: psql -d summitflow -f migrations/026_tech_debt_cleanup.sql

-- Drop unused columns from prompts table
ALTER TABLE prompts
  DROP COLUMN IF EXISTS verification_enabled,
  DROP COLUMN IF EXISTS verification_agent,
  DROP COLUMN IF EXISTS verification_model,
  DROP COLUMN IF EXISTS verification_prompt;

-- Drop legacy tables (superseded by explorer_entries)
DROP TABLE IF EXISTS file_audit CASCADE;
DROP TABLE IF EXISTS scanner_database CASCADE;
DROP TABLE IF EXISTS scanner_api CASCADE;
DROP TABLE IF EXISTS scanner_celery CASCADE;
DROP TABLE IF EXISTS sitemap_health_history CASCADE;

-- Verify cleanup
SELECT 'Tech debt cleanup complete' as status,
       (SELECT COUNT(*) FROM explorer_entries) as explorer_entries_count;
