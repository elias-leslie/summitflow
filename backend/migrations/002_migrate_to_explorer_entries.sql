-- Migration: Migrate existing data to explorer_entries
-- Created: 2025-12-18
-- Purpose: Move data from legacy tables to unified explorer_entries schema
--
-- Source tables:
-- - file_audit → explorer_entries (type=file)
-- - scanner_database → explorer_entries (type=table)
-- - scanner_celery → explorer_entries (type=task)
-- - sitemap_entries + scanner_api → explorer_entries (type=endpoint)
--
-- Run with: psql -d summitflow -f migrations/002_migrate_to_explorer_entries.sql
-- Or via Python: backend/.venv/bin/python -c "exec(open('migrations/002_migrate_to_explorer_entries.sql').read())"

-- ============================================================
-- Step 1: Ensure explorer_entries table exists
-- ============================================================
-- (Already created by 001_create_explorer_tables.sql)

-- ============================================================
-- Step 2: Migrate file_audit → explorer_entries (type=file)
-- ============================================================
INSERT INTO explorer_entries (
    project_id, entry_type, path, name, health_status, metadata,
    last_scanned_at, created_at, updated_at
)
SELECT
    project_id,
    'file' as entry_type,
    path,
    -- Extract name from path (last segment)
    CASE
        WHEN position('/' in path) > 0 THEN substring(path from '([^/]+)$')
        ELSE path
    END as name,
    -- Map stale_status to health_status
    CASE
        WHEN bloat_level = 'critical' THEN 'error'
        WHEN bloat_level = 'warning' THEN 'warning'
        WHEN stale_status = 'orphan' THEN 'error'
        WHEN stale_status = 'stale' THEN 'warning'
        WHEN stale_status = 'fresh' THEN 'healthy'
        ELSE 'unknown'
    END as health_status,
    jsonb_build_object(
        'is_directory', is_directory,
        'extension', extension,
        'size_bytes', size_bytes,
        'lines_of_code', lines_of_code,
        'file_count', file_count,
        'bloat_level', bloat_level,
        'stale_status', stale_status,
        'last_commit_days', last_commit_days
    ) as metadata,
    scanned_at as last_scanned_at,
    scanned_at as created_at,
    scanned_at as updated_at
FROM file_audit
WHERE NOT EXISTS (
    SELECT 1 FROM explorer_entries e
    WHERE e.project_id = file_audit.project_id
      AND e.entry_type = 'file'
      AND e.path = file_audit.path
)
ON CONFLICT (project_id, entry_type, path) DO UPDATE SET
    health_status = EXCLUDED.health_status,
    metadata = EXCLUDED.metadata,
    last_scanned_at = EXCLUDED.last_scanned_at,
    updated_at = NOW();

-- ============================================================
-- Step 3: Migrate scanner_database → explorer_entries (type=table)
-- ============================================================
INSERT INTO explorer_entries (
    project_id, entry_type, path, name, health_status, metadata,
    last_scanned_at, created_at, updated_at
)
SELECT
    project_id,
    'table' as entry_type,
    table_name as path,
    table_name as name,
    health_status,
    jsonb_build_object(
        'row_count', row_count,
        'column_count', total_columns,
        'columns', columns,
        'columns_with_data', columns_with_data,
        'columns_mostly_null', columns_mostly_null,
        'completeness_pct', completeness_pct,
        'freshness_days', days_since_update,
        'category', category,
        'relationships', jsonb_build_object(
            'referenced_by', fk_referenced_by
        )
    ) as metadata,
    last_scanned_at,
    created_at,
    updated_at
FROM scanner_database
WHERE NOT EXISTS (
    SELECT 1 FROM explorer_entries e
    WHERE e.project_id = scanner_database.project_id
      AND e.entry_type = 'table'
      AND e.path = scanner_database.table_name
)
ON CONFLICT (project_id, entry_type, path) DO UPDATE SET
    health_status = EXCLUDED.health_status,
    metadata = EXCLUDED.metadata,
    last_scanned_at = EXCLUDED.last_scanned_at,
    updated_at = NOW();

-- ============================================================
-- Step 4: Migrate scanner_celery → explorer_entries (type=task)
-- ============================================================
INSERT INTO explorer_entries (
    project_id, entry_type, path, name, health_status, metadata,
    last_scanned_at, created_at, updated_at
)
SELECT
    project_id,
    'task' as entry_type,
    task_name as path,
    -- Extract short name from task_name
    CASE
        WHEN position('.' in task_name) > 0 THEN substring(task_name from '([^.]+)$')
        ELSE task_name
    END as name,
    health_status,
    jsonb_build_object(
        'task_path', task_path,
        'function_name', function_name,
        'schedule_type', CASE
            WHEN schedule_crontab IS NOT NULL THEN 'crontab'
            WHEN schedule_interval_seconds IS NOT NULL THEN 'interval'
            ELSE NULL
        END,
        'schedule_value', COALESCE(schedule_crontab, schedule_interval_seconds::text),
        'schedule_human', schedule_description,
        'last_run_at', last_run_at,
        'success_count_7d', success_count_7d,
        'failure_count_7d', failure_count_7d,
        'success_rate_pct', success_rate_pct,
        'reads_tables', reads_from_tables,
        'writes_tables', populates_tables,
        'depends_on_tasks', depends_on_tasks,
        'called_by', called_by
    ) as metadata,
    last_scanned_at,
    created_at,
    updated_at
FROM scanner_celery
WHERE NOT EXISTS (
    SELECT 1 FROM explorer_entries e
    WHERE e.project_id = scanner_celery.project_id
      AND e.entry_type = 'task'
      AND e.path = scanner_celery.task_name
)
ON CONFLICT (project_id, entry_type, path) DO UPDATE SET
    health_status = EXCLUDED.health_status,
    metadata = EXCLUDED.metadata,
    last_scanned_at = EXCLUDED.last_scanned_at,
    updated_at = NOW();

-- ============================================================
-- Step 5: Migrate sitemap_entries → explorer_entries (type=endpoint)
-- Merges sitemap (runtime health) with scanner_api (static analysis)
-- ============================================================
INSERT INTO explorer_entries (
    project_id, entry_type, path, name, health_status, metadata,
    last_scanned_at, created_at, updated_at
)
SELECT
    s.project_id,
    'endpoint' as entry_type,
    -- Create unique path combining method and path
    s.method || ' ' || s.path as path,
    s.path as name,
    s.health_status,
    jsonb_build_object(
        'method', s.method,
        'port', s.port,
        'endpoint_type', s.entry_type,
        'source_file', a.route_file,
        'function_name', a.function_name,
        'http_status', s.http_status,
        'response_time_ms', s.response_time_ms,
        'console_errors', s.console_errors,
        'console_warnings', s.console_warnings,
        'depends_on_tables', COALESCE(a.depends_on_tables, '[]'::jsonb),
        'called_by_frontend', COALESCE(a.frontend_callers, '[]'::jsonb),
        'last_health_check', s.last_checked_at
    ) as metadata,
    COALESCE(a.last_scanned_at, s.last_checked_at) as last_scanned_at,
    s.created_at,
    s.updated_at
FROM sitemap_entries s
LEFT JOIN scanner_api a ON
    s.project_id = a.project_id
    AND s.path = a.endpoint_path
    AND s.method = a.http_method
WHERE NOT EXISTS (
    SELECT 1 FROM explorer_entries e
    WHERE e.project_id = s.project_id
      AND e.entry_type = 'endpoint'
      AND e.path = (s.method || ' ' || s.path)
)
ON CONFLICT (project_id, entry_type, path) DO UPDATE SET
    health_status = EXCLUDED.health_status,
    metadata = EXCLUDED.metadata,
    last_scanned_at = EXCLUDED.last_scanned_at,
    updated_at = NOW();

-- ============================================================
-- Step 6: Add scanner_api entries that aren't in sitemap
-- These are static routes that haven't been health-checked yet
-- ============================================================
INSERT INTO explorer_entries (
    project_id, entry_type, path, name, health_status, metadata,
    last_scanned_at, created_at, updated_at
)
SELECT
    a.project_id,
    'endpoint' as entry_type,
    a.http_method || ' ' || a.endpoint_path as path,
    a.endpoint_path as name,
    a.health_status,
    jsonb_build_object(
        'method', a.http_method,
        'endpoint_type', 'api',
        'source_file', a.route_file,
        'function_name', a.function_name,
        'depends_on_tables', a.depends_on_tables,
        'called_by_frontend', a.frontend_callers
    ) as metadata,
    a.last_scanned_at,
    a.created_at,
    a.updated_at
FROM scanner_api a
WHERE NOT EXISTS (
    SELECT 1 FROM sitemap_entries s
    WHERE s.project_id = a.project_id
      AND s.path = a.endpoint_path
      AND s.method = a.http_method
)
AND NOT EXISTS (
    SELECT 1 FROM explorer_entries e
    WHERE e.project_id = a.project_id
      AND e.entry_type = 'endpoint'
      AND e.path = (a.http_method || ' ' || a.endpoint_path)
)
ON CONFLICT (project_id, entry_type, path) DO UPDATE SET
    health_status = EXCLUDED.health_status,
    metadata = EXCLUDED.metadata,
    last_scanned_at = EXCLUDED.last_scanned_at,
    updated_at = NOW();

-- ============================================================
-- Verification: Count migrated records
-- ============================================================
SELECT
    'Migration Complete' as status,
    entry_type,
    COUNT(*) as count
FROM explorer_entries
GROUP BY entry_type
ORDER BY entry_type;
