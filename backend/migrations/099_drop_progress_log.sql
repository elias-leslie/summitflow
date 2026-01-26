-- Migration: Remove deprecated progress_log column
-- Purpose: progress_log TEXT is replaced by unified events table
-- See: task-6f952310 - Implement unified events system

-- Drop the progress_log column from tasks table
ALTER TABLE tasks DROP COLUMN IF EXISTS progress_log;
