import type { TaskType } from '@/lib/api/tasks-types'

export type Complexity = 'simple' | 'standard' | 'complex'

export interface IdeationTaskData {
  title: string
  description: string
  priority: number
  task_type: TaskType
  labels: string[]
  complexity: Complexity
}

export interface IdeationTaskResponse {
  task_id: string
  project_id: string
  status: string
  dispatched: boolean
  dispatch_stage: string | null
}

export interface TaskIdeationDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
}

export interface TaskSummaryCardProps {
  taskData: IdeationTaskData
  isSubmitting: boolean
  error: string | null
  onUpdateField: <K extends keyof IdeationTaskData>(
    field: K,
    value: IdeationTaskData[K],
  ) => void
  onAddLabel: (label: string) => void
  onRemoveLabel: (label: string) => void
  onCreateAndStart: () => void
  onBackToChat: () => void
}

export const PRIORITY_OPTIONS = [
  { value: '0', label: 'P0 - Critical' },
  { value: '1', label: 'P1 - High' },
  { value: '2', label: 'P2 - Medium' },
  { value: '3', label: 'P3 - Low' },
  { value: '4', label: 'P4 - Backlog' },
]

export const TYPE_OPTIONS: { value: TaskType; label: string }[] = [
  { value: 'feature', label: 'Feature' },
  { value: 'bug', label: 'Bug' },
  { value: 'task', label: 'Task' },
  { value: 'refactor', label: 'Refactor' },
  { value: 'debt', label: 'Tech Debt' },
  { value: 'regression', label: 'Regression' },
]

export const COMPLEXITY_OPTIONS: { value: Complexity; label: string }[] = [
  { value: 'simple', label: 'Simple' },
  { value: 'standard', label: 'Standard' },
  { value: 'complex', label: 'Complex' },
]

export const AGENT_SLUG = 'ideator'
export const CHAT_TITLE = 'Task Ideation'
export const CREATE_TASK_TOOL_NAME = 'create_task'
export const DEFAULT_PRIORITY = 2
export const DEFAULT_TASK_TYPE: TaskType = 'task'
export const DEFAULT_COMPLEXITY: Complexity = 'standard'
