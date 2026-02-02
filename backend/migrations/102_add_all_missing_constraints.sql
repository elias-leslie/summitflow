-- Migration 102: Add ALL missing primary keys and unique constraints
-- This is a comprehensive fix for all 25 tables without proper constraints
-- Created: 2026-02-01
--
-- IMPORTANT: Run deduplication queries BEFORE this migration if duplicates exist

-- =============================================================================
-- STEP 1: Check for duplicates and clean up if needed
-- =============================================================================

-- Deduplicate agent_sessions (keep newest by ctid)
DELETE FROM agent_sessions a USING agent_sessions b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate backup_schedules by project_id (keep newest)
DELETE FROM backup_schedules a USING backup_schedules b
WHERE a.project_id = b.project_id AND a.ctid < b.ctid;

-- Deduplicate backups by id
DELETE FROM backups a USING backups b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate celery_taskmeta by id and task_id
DELETE FROM celery_taskmeta a USING celery_taskmeta b
WHERE a.id = b.id AND a.ctid < b.ctid;
DELETE FROM celery_taskmeta a USING celery_taskmeta b
WHERE a.task_id = b.task_id AND a.ctid < b.ctid;

-- Deduplicate events by id
DELETE FROM events a USING events b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate explorer_entries by id and by (project_id, entry_type, path)
DELETE FROM explorer_entries a USING explorer_entries b
WHERE a.id = b.id AND a.ctid < b.ctid;
DELETE FROM explorer_entries a USING explorer_entries b
WHERE a.project_id = b.project_id AND a.entry_type = b.entry_type AND a.path = b.path AND a.ctid < b.ctid;

-- Deduplicate ideas by id
DELETE FROM ideas a USING ideas b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate migration_backup by id
DELETE FROM migration_backup a USING migration_backup b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate mockups by id
DELETE FROM mockups a USING mockups b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate qa_issues by id
DELETE FROM qa_issues a USING qa_issues b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate quality_check_results by id
DELETE FROM quality_check_results a USING quality_check_results b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate scan_history by id
DELETE FROM scan_history a USING scan_history b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate scan_states by project_id (keep newest)
DELETE FROM scan_states a USING scan_states b
WHERE a.project_id = b.project_id AND a.ctid < b.ctid;

-- Deduplicate subtask_citations by id
DELETE FROM subtask_citations a USING subtask_citations b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate subtask_dependencies by id and by (subtask_id, depends_on_subtask_id)
DELETE FROM subtask_dependencies a USING subtask_dependencies b
WHERE a.id = b.id AND a.ctid < b.ctid;
DELETE FROM subtask_dependencies a USING subtask_dependencies b
WHERE a.subtask_id = b.subtask_id AND a.depends_on_subtask_id = b.depends_on_subtask_id AND a.ctid < b.ctid;

-- Deduplicate subtask_summaries by id and by subtask_id
DELETE FROM subtask_summaries a USING subtask_summaries b
WHERE a.id = b.id AND a.ctid < b.ctid;
DELETE FROM subtask_summaries a USING subtask_summaries b
WHERE a.subtask_id = b.subtask_id AND a.ctid < b.ctid;

-- Deduplicate task_dependencies by id and by (task_id, depends_on_task_id, dependency_type)
DELETE FROM task_dependencies a USING task_dependencies b
WHERE a.id = b.id AND a.ctid < b.ctid;
DELETE FROM task_dependencies a USING task_dependencies b
WHERE a.task_id = b.task_id AND a.depends_on_task_id = b.depends_on_task_id
  AND COALESCE(a.dependency_type, '') = COALESCE(b.dependency_type, '') AND a.ctid < b.ctid;

-- Deduplicate task_labels by (task_id, label)
DELETE FROM task_labels a USING task_labels b
WHERE a.task_id = b.task_id AND a.label = b.label AND a.ctid < b.ctid;

-- Deduplicate task_subtask_steps by id and by (subtask_id, step_number)
DELETE FROM task_subtask_steps a USING task_subtask_steps b
WHERE a.id = b.id AND a.ctid < b.ctid;
DELETE FROM task_subtask_steps a USING task_subtask_steps b
WHERE a.subtask_id = b.subtask_id AND a.step_number = b.step_number AND a.ctid < b.ctid;

-- Deduplicate task_subtasks by id (unique on task_id, subtask_id already exists)
DELETE FROM task_subtasks a USING task_subtasks b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate terminal_panes by id
DELETE FROM terminal_panes a USING terminal_panes b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate terminal_project_settings by project_id
DELETE FROM terminal_project_settings a USING terminal_project_settings b
WHERE a.project_id = b.project_id AND a.ctid < b.ctid;

-- Deduplicate terminal_sessions by id
DELETE FROM terminal_sessions a USING terminal_sessions b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- Deduplicate user_prompts by id
DELETE FROM user_prompts a USING user_prompts b
WHERE a.id = b.id AND a.ctid < b.ctid;

-- =============================================================================
-- STEP 2: Add PRIMARY KEY constraints
-- =============================================================================

-- Tables with serial/int id columns
ALTER TABLE agent_sessions ADD PRIMARY KEY (id);
ALTER TABLE backup_schedules ADD PRIMARY KEY (id);
ALTER TABLE celery_taskmeta ADD PRIMARY KEY (id);
ALTER TABLE explorer_entries ADD PRIMARY KEY (id);
ALTER TABLE migration_backup ADD PRIMARY KEY (id);
ALTER TABLE mockups ADD PRIMARY KEY (id);
ALTER TABLE qa_issues ADD PRIMARY KEY (id);
ALTER TABLE quality_check_results ADD PRIMARY KEY (id);
ALTER TABLE scan_history ADD PRIMARY KEY (id);
ALTER TABLE subtask_dependencies ADD PRIMARY KEY (id);
ALTER TABLE subtask_summaries ADD PRIMARY KEY (id);
ALTER TABLE task_dependencies ADD PRIMARY KEY (id);
ALTER TABLE task_subtask_steps ADD PRIMARY KEY (id);

-- Tables with text/varchar id columns
ALTER TABLE backups ADD PRIMARY KEY (id);
ALTER TABLE ideas ADD PRIMARY KEY (id);
ALTER TABLE task_subtasks ADD PRIMARY KEY (id);

-- Tables with UUID id columns
ALTER TABLE events ADD PRIMARY KEY (id);
ALTER TABLE subtask_citations ADD PRIMARY KEY (id);
ALTER TABLE terminal_panes ADD PRIMARY KEY (id);
ALTER TABLE terminal_sessions ADD PRIMARY KEY (id);
ALTER TABLE user_prompts ADD PRIMARY KEY (id);

-- Tables with single-column natural keys (one row per entity)
ALTER TABLE scan_states ADD PRIMARY KEY (project_id);
ALTER TABLE terminal_project_settings ADD PRIMARY KEY (project_id);

-- Tables with composite natural keys
ALTER TABLE task_labels ADD PRIMARY KEY (task_id, label);

-- Alembic version table (special case - single column)
ALTER TABLE alembic_version ADD PRIMARY KEY (version_num);

-- =============================================================================
-- STEP 3: Add UNIQUE constraints needed for ON CONFLICT
-- =============================================================================

-- backup_schedules: ON CONFLICT (project_id)
ALTER TABLE backup_schedules ADD CONSTRAINT backup_schedules_project_id_key UNIQUE (project_id);

-- celery_taskmeta: ON CONFLICT (task_id) - Celery needs this
ALTER TABLE celery_taskmeta ADD CONSTRAINT celery_taskmeta_task_id_key UNIQUE (task_id);

-- explorer_entries: ON CONFLICT (project_id, entry_type, path)
ALTER TABLE explorer_entries ADD CONSTRAINT explorer_entries_project_entry_path_key
    UNIQUE (project_id, entry_type, path);

-- subtask_dependencies: ON CONFLICT (subtask_id, depends_on_subtask_id)
ALTER TABLE subtask_dependencies ADD CONSTRAINT subtask_dependencies_subtask_depends_key
    UNIQUE (subtask_id, depends_on_subtask_id);

-- subtask_summaries: ON CONFLICT (subtask_id)
ALTER TABLE subtask_summaries ADD CONSTRAINT subtask_summaries_subtask_id_key UNIQUE (subtask_id);

-- task_dependencies: ON CONFLICT (task_id, depends_on_task_id, dependency_type)
ALTER TABLE task_dependencies ADD CONSTRAINT task_dependencies_task_depends_type_key
    UNIQUE (task_id, depends_on_task_id, dependency_type);

-- task_subtask_steps: ON CONFLICT (subtask_id, step_number)
ALTER TABLE task_subtask_steps ADD CONSTRAINT task_subtask_steps_subtask_step_key
    UNIQUE (subtask_id, step_number);

-- =============================================================================
-- STEP 4: Verification query
-- =============================================================================

SELECT
    t.table_name,
    CASE WHEN pk.cnt > 0 THEN 'YES' ELSE 'NO' END as has_pk,
    COALESCE(uk.cnt, 0) as unique_constraints
FROM information_schema.tables t
LEFT JOIN (
    SELECT table_name, COUNT(*) as cnt
    FROM information_schema.table_constraints
    WHERE constraint_type = 'PRIMARY KEY' AND table_schema = 'public'
    GROUP BY table_name
) pk ON t.table_name = pk.table_name
LEFT JOIN (
    SELECT table_name, COUNT(*) as cnt
    FROM information_schema.table_constraints
    WHERE constraint_type = 'UNIQUE' AND table_schema = 'public'
    GROUP BY table_name
) uk ON t.table_name = uk.table_name
WHERE t.table_schema = 'public'
  AND t.table_type = 'BASE TABLE'
  AND t.table_name IN (
    'agent_sessions', 'alembic_version', 'backup_schedules', 'backups',
    'celery_taskmeta', 'events', 'explorer_entries', 'ideas',
    'migration_backup', 'mockups', 'qa_issues', 'quality_check_results',
    'scan_history', 'scan_states', 'subtask_citations', 'subtask_dependencies',
    'subtask_summaries', 'task_dependencies', 'task_labels', 'task_subtask_steps',
    'task_subtasks', 'terminal_panes', 'terminal_project_settings',
    'terminal_sessions', 'user_prompts'
  )
ORDER BY t.table_name;
