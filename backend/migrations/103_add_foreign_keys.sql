-- Migration 103: Add foreign key constraints
-- These FKs were defined in original migrations but not created
-- Applied: 2026-02-01
-- Result: 31 FKs added

-- =============================================================================
-- STEP 1: Clean up orphaned data (run before FK creation)
-- =============================================================================

-- Order matters: delete children before parents

-- Subtask-level orphans
DELETE FROM task_subtask_steps WHERE subtask_id NOT IN (SELECT id FROM task_subtasks);
DELETE FROM subtask_dependencies WHERE subtask_id NOT IN (SELECT id FROM task_subtasks);
DELETE FROM subtask_dependencies WHERE depends_on_subtask_id NOT IN (SELECT id FROM task_subtasks);
DELETE FROM subtask_summaries WHERE subtask_id NOT IN (SELECT id FROM task_subtasks);
DELETE FROM subtask_citations WHERE subtask_id NOT IN (SELECT id FROM task_subtasks);

-- Task-level orphans
DELETE FROM task_subtasks WHERE task_id NOT IN (SELECT id FROM tasks);
DELETE FROM task_spirit WHERE task_id NOT IN (SELECT id FROM tasks);
DELETE FROM task_labels WHERE task_id NOT IN (SELECT id FROM tasks);
DELETE FROM task_dependencies WHERE task_id NOT IN (SELECT id FROM tasks);
DELETE FROM task_dependencies WHERE depends_on_task_id NOT IN (SELECT id FROM tasks);
DELETE FROM ideas WHERE task_id IS NOT NULL AND task_id NOT IN (SELECT id FROM tasks);
DELETE FROM mockups WHERE task_id IS NOT NULL AND task_id NOT IN (SELECT id FROM tasks);
DELETE FROM quality_check_results WHERE escalation_task_id IS NOT NULL AND escalation_task_id NOT IN (SELECT id FROM tasks);

-- Project-level orphans
DELETE FROM events WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM ideas WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM mockups WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM backups WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM backup_schedules WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM explorer_entries WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM qa_issues WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM quality_check_results WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM scan_history WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM scan_states WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM refactor_sessions WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM user_prompts WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM agent_sessions WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM notifications WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM project_agent_config WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM sitemap_entries WHERE project_id NOT IN (SELECT id FROM projects);
DELETE FROM code_health_lists WHERE project_id NOT IN (SELECT id FROM projects);

-- Explorer-level orphans
DELETE FROM explorer_sub_elements WHERE explorer_entry_id NOT IN (SELECT id FROM explorer_entries);
DELETE FROM qa_issues WHERE entry_id IS NOT NULL AND entry_id NOT IN (SELECT id FROM explorer_entries);

-- =============================================================================
-- STEP 2: Add foreign key constraints
-- =============================================================================

-- Task hierarchy
ALTER TABLE task_subtasks ADD CONSTRAINT task_subtasks_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;
ALTER TABLE task_subtask_steps ADD CONSTRAINT task_subtask_steps_subtask_id_fkey
    FOREIGN KEY (subtask_id) REFERENCES task_subtasks(id) ON DELETE CASCADE;
ALTER TABLE task_spirit ADD CONSTRAINT task_spirit_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;
ALTER TABLE task_labels ADD CONSTRAINT task_labels_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;
ALTER TABLE task_dependencies ADD CONSTRAINT task_dependencies_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;
ALTER TABLE task_dependencies ADD CONSTRAINT task_dependencies_depends_on_task_id_fkey
    FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id) ON DELETE CASCADE;

-- Subtask hierarchy
ALTER TABLE subtask_dependencies ADD CONSTRAINT subtask_dependencies_subtask_id_fkey
    FOREIGN KEY (subtask_id) REFERENCES task_subtasks(id) ON DELETE CASCADE;
ALTER TABLE subtask_dependencies ADD CONSTRAINT subtask_dependencies_depends_on_subtask_id_fkey
    FOREIGN KEY (depends_on_subtask_id) REFERENCES task_subtasks(id) ON DELETE CASCADE;
ALTER TABLE subtask_summaries ADD CONSTRAINT subtask_summaries_subtask_id_fkey
    FOREIGN KEY (subtask_id) REFERENCES task_subtasks(id) ON DELETE CASCADE;
ALTER TABLE subtask_citations ADD CONSTRAINT subtask_citations_subtask_id_fkey
    FOREIGN KEY (subtask_id) REFERENCES task_subtasks(id) ON DELETE CASCADE;

-- Project references
ALTER TABLE tasks ADD CONSTRAINT tasks_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE tasks ADD CONSTRAINT tasks_parent_task_id_fkey
    FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE ideas ADD CONSTRAINT ideas_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE ideas ADD CONSTRAINT ideas_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE events ADD CONSTRAINT events_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE backups ADD CONSTRAINT backups_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE backup_schedules ADD CONSTRAINT backup_schedules_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE mockups ADD CONSTRAINT mockups_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE mockups ADD CONSTRAINT mockups_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE explorer_entries ADD CONSTRAINT explorer_entries_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE explorer_sub_elements ADD CONSTRAINT explorer_sub_elements_explorer_entry_id_fkey
    FOREIGN KEY (explorer_entry_id) REFERENCES explorer_entries(id) ON DELETE CASCADE;
ALTER TABLE qa_issues ADD CONSTRAINT qa_issues_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE qa_issues ADD CONSTRAINT qa_issues_entry_id_fkey
    FOREIGN KEY (entry_id) REFERENCES explorer_entries(id) ON DELETE SET NULL;
ALTER TABLE quality_check_results ADD CONSTRAINT quality_check_results_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE quality_check_results ADD CONSTRAINT quality_check_results_escalation_task_id_fkey
    FOREIGN KEY (escalation_task_id) REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE scan_history ADD CONSTRAINT scan_history_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE scan_states ADD CONSTRAINT scan_states_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE refactor_sessions ADD CONSTRAINT refactor_sessions_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE user_prompts ADD CONSTRAINT user_prompts_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE agent_sessions ADD CONSTRAINT agent_sessions_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE notifications ADD CONSTRAINT notifications_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE project_agent_config ADD CONSTRAINT project_agent_config_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE sitemap_entries ADD CONSTRAINT sitemap_entries_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE code_health_lists ADD CONSTRAINT code_health_lists_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
