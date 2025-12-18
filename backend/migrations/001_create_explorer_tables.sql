-- Migration: Create Explorer Foundation Tables
-- Created: 2025-12-18
-- Purpose: Unified explorer_entries and explorer_relationships tables for Explorer Foundation Rebuild

-- ============================================================
-- explorer_entries: Primary table for all explorer entity types
-- Types: 'file', 'table', 'task', 'endpoint'
-- ============================================================
CREATE TABLE IF NOT EXISTS explorer_entries (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Identity
    entry_type VARCHAR(20) NOT NULL,  -- 'file', 'table', 'task', 'endpoint'
    path VARCHAR(500) NOT NULL,        -- Unique identifier within type
    name VARCHAR(255) NOT NULL,        -- Display name

    -- Common fields
    health_status VARCHAR(20) DEFAULT 'unknown',  -- 'healthy', 'warning', 'error', 'unknown'
    last_scanned_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Type-specific data (flexible JSONB)
    metadata JSONB DEFAULT '{}',

    -- Composite unique constraint
    UNIQUE(project_id, entry_type, path)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_explorer_entries_project_type ON explorer_entries(project_id, entry_type);
CREATE INDEX IF NOT EXISTS idx_explorer_entries_health ON explorer_entries(project_id, health_status);
CREATE INDEX IF NOT EXISTS idx_explorer_entries_metadata ON explorer_entries USING GIN (metadata);

-- ============================================================
-- explorer_relationships: Cross-entity relationships
-- Tracks: imports, calls, queries, references
-- ============================================================
CREATE TABLE IF NOT EXISTS explorer_relationships (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL,

    -- Source entry
    source_type VARCHAR(20) NOT NULL,
    source_path VARCHAR(500) NOT NULL,

    -- Target entry
    target_type VARCHAR(20) NOT NULL,
    target_path VARCHAR(500) NOT NULL,

    -- Relationship type
    relationship VARCHAR(50) NOT NULL,  -- 'imports', 'calls', 'queries', 'references'

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Composite unique constraint
    UNIQUE(project_id, source_type, source_path, target_type, target_path, relationship)
);

-- Index for relationship lookups
CREATE INDEX IF NOT EXISTS idx_explorer_rel_source ON explorer_relationships(project_id, source_type, source_path);
CREATE INDEX IF NOT EXISTS idx_explorer_rel_target ON explorer_relationships(project_id, target_type, target_path);
