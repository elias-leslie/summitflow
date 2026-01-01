# Archived Migration Scripts

These scripts are historical and have already been run. They are kept for reference.

## migrate_tdd_architecture.py

Migrated from the old task-based TDD approach to the new capability-centric model:
- Created `acceptance_criteria` table
- Created `capability_criteria` junction table
- Created `criterion_tests` junction table
- Migrated existing task acceptance_criteria JSONB to new tables

## migrate_plan_content_to_subtasks.py

Migrated task plan_content field to the structured `task_subtasks` table:
- Parsed plan_content markdown into subtasks
- Created entries in `task_subtasks` table
- Preserved phase and step information
