-- Migration 085: Migrate mockup evidence records to mockups table
-- One-time migration to move mockup data from evidence to dedicated mockups table

-- Insert mockups from evidence table, mapping fields appropriately
INSERT INTO mockups (
    project_id,
    mockup_id,
    name,
    description,
    mockup_type,
    file_path,
    content,
    status,
    task_id,
    version,
    generator,
    created_at,
    updated_at
)
SELECT
    e.project_id,
    'mk-' || substring(e.evidence_id from 4) as mockup_id,
    COALESCE(ee.name, 'Migrated mockup ' || e.evidence_id) as name,
    NULL as description,
    'page' as mockup_type,
    e.file_path,
    NULL as content,
    CASE e.mockup_status
        WHEN 'generated' THEN 'generated'
        WHEN 'pending_approval' THEN 'pending_approval'
        WHEN 'approved' THEN 'approved'
        WHEN 'rejected' THEN 'rejected'
        ELSE 'generated'
    END as status,
    e.task_id,
    e.version,
    'migrated-from-evidence' as generator,
    e.captured_at as created_at,
    COALESCE(e.updated_at, e.captured_at) as updated_at
FROM evidence e
LEFT JOIN explorer_entries ee ON e.explorer_entry_id = ee.id
WHERE e.evidence_type = 'mockup'
  AND e.is_current = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM mockups m
    WHERE m.project_id = e.project_id
      AND m.mockup_id = 'mk-' || substring(e.evidence_id from 4)
  );

-- Log migration completion
DO $$
DECLARE
    migrated_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO migrated_count FROM mockups WHERE generator = 'migrated-from-evidence';
    RAISE NOTICE 'Migrated % mockups from evidence table', migrated_count;
END $$;
