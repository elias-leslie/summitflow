-- Migration: Add generated_spec column to roundtable_sessions
-- This column stores the ephemeral TDD spec generated during roundtable sessions
-- The spec can be reviewed, adjusted, and then accepted to create permanent entities

ALTER TABLE roundtable_sessions ADD COLUMN IF NOT EXISTS generated_spec JSONB DEFAULT NULL;
