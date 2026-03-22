/**
 * Shared test factories — single source of truth for test data.
 *
 * Every test that needs a Task (or other domain object) should import from here
 * instead of defining its own factory. When the Task interface changes, fix it
 * once here.
 */

import type { Task } from '@/lib/api/tasks'

export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    project_id: 'summitflow',
    capability_id: null,
    title: 'Test task',
    description: null,
    status: 'pending',
    plan_content: null,
    progress_log: null,
    error_message: null,
    branch_name: null,
    commits: [],
    total_sessions: 0,
    total_tokens_used: 0,
    created_at: null,
    updated_at: null,
    started_at: null,
    completed_at: null,
    priority: 50,
    labels: [],
    task_type: 'task',
    parent_task_id: null,
    ...overrides,
  }
}
