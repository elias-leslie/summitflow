-- Migration: 014_cleanup_test_diary_data.sql
-- Purpose: Clear test/development diary entries that pollute real data
-- Date: 2025-12-23

-- Delete test diary entries with 'test-' or 'fresh-' session prefixes
DELETE FROM session_diary WHERE session_id LIKE 'test-%';
DELETE FROM session_diary WHERE session_id LIKE 'fresh-%';

-- Also clean up batch test entries
DELETE FROM session_diary WHERE session_id LIKE 'batch-test-%';
