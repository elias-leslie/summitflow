// Utility functions for autonomous settings

import type { TaskType } from '@/lib/api/tasks'

export const TASK_TYPES: { value: TaskType; label: string }[] = [
  { value: 'feature', label: 'Feature' },
  { value: 'bug', label: 'Bug' },
  { value: 'task', label: 'Task' },
  { value: 'refactor', label: 'Refactor' },
  { value: 'debt', label: 'Tech Debt' },
  { value: 'regression', label: 'Regression' },
]
