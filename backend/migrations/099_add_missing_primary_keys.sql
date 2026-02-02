-- Migration: Add missing primary key constraints
-- Issue: Tables were created without PRIMARY KEY constraints, allowing duplicates
-- Fixed: 2026-02-01 after discovering 355 duplicate tasks, 907 duplicate projects

-- Note: Run deduplication BEFORE this migration if duplicates exist:
-- DELETE FROM tasks t1 USING tasks t2 WHERE t1.id = t2.id AND t1.ctid > t2.ctid;
-- DELETE FROM projects p1 USING projects p2 WHERE p1.id = p2.id AND p1.ctid > p2.ctid;
-- DELETE FROM task_spirit ts1 USING task_spirit ts2 WHERE ts1.task_id = ts2.task_id AND ts1.ctid > ts2.ctid;

-- Add primary keys (will fail if duplicates exist)
ALTER TABLE tasks ADD PRIMARY KEY (id);
ALTER TABLE projects ADD PRIMARY KEY (id);
ALTER TABLE task_spirit ADD PRIMARY KEY (task_id);

-- Verify
SELECT 'tasks' as tbl, count(*) as total, count(distinct id) as unique_ids FROM tasks
UNION ALL
SELECT 'projects', count(*), count(distinct id) FROM projects
UNION ALL  
SELECT 'task_spirit', count(*), count(distinct task_id) FROM task_spirit;
