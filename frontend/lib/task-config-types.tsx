/**
 * Task type and status configuration with React icon nodes.
 */

import {
  AlertTriangle,
  ArrowDownCircle,
  Bug,
  Check,
  CheckCircle2,
  CheckSquare,
  Clock,
  ListTodo,
  Loader2,
  Package,
  Play,
  RefreshCw,
  X,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { TaskStatus, TaskType } from '@/lib/api'

// ============================================================================
// Task Type Configuration
// ============================================================================

export interface TaskTypeConfig {
  icon: React.ReactNode
  label: string
  className: string
}

export const taskTypeConfig: Record<TaskType, TaskTypeConfig> = {
  feature: {
    icon: <Package className="h-4 w-4" />,
    label: 'Feature',
    className: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  },
  bug: {
    icon: <Bug className="h-4 w-4" />,
    label: 'Bug',
    className: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  },
  task: {
    icon: <CheckSquare className="h-4 w-4" />,
    label: 'Task',
    className: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  },
  refactor: {
    icon: <RefreshCw className="h-4 w-4" />,
    label: 'Refactor',
    className: 'bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30',
  },
  debt: {
    icon: <AlertTriangle className="h-4 w-4" />,
    label: 'Tech Debt',
    className: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  regression: {
    icon: <ArrowDownCircle className="h-4 w-4" />,
    label: 'Regression',
    className: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
}

/** Small icon variant for compact views (TaskCard) */
export interface TaskTypeConfigSmall {
  icon: React.ReactNode
  className: string
}

export const taskTypeConfigSmall: Record<TaskType, TaskTypeConfigSmall> = {
  feature: {
    icon: <Package className="h-3.5 w-3.5" />,
    className: 'text-purple-400',
  },
  bug: {
    icon: <Bug className="h-3.5 w-3.5" />,
    className: 'text-rose-400',
  },
  task: {
    icon: <CheckSquare className="h-3.5 w-3.5" />,
    className: 'text-blue-400',
  },
  refactor: {
    icon: <RefreshCw className="h-3.5 w-3.5" />,
    className: 'text-phosphor-400',
  },
  debt: {
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    className: 'text-amber-400',
  },
  regression: {
    icon: <ArrowDownCircle className="h-3.5 w-3.5" />,
    className: 'text-orange-400',
  },
}

export function getTaskTypeConfig(taskType: TaskType): TaskTypeConfig {
  return taskTypeConfig[taskType] || taskTypeConfig.task
}

export function getTaskTypeConfigSmall(
  taskType: TaskType,
): TaskTypeConfigSmall {
  return taskTypeConfigSmall[taskType] || taskTypeConfigSmall.task
}

// ============================================================================
// Task Status Configuration (for TaskCard - includes title)
// ============================================================================

export interface TaskStatusCardConfig {
  icon: React.ReactNode | null
  className: string
  title: string
}

export const taskStatusCardConfig: Record<TaskStatus, TaskStatusCardConfig> = {
  pending: { icon: null, className: '', title: '' },
  running: {
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    className: 'text-blue-400',
    title: 'Task running',
  },
  completed: {
    icon: <Check className="h-3.5 w-3.5" />,
    className: 'text-green-400',
    title: 'Task completed',
  },
  failed: {
    icon: <X className="h-3.5 w-3.5" />,
    className: 'text-rose-400',
    title: 'Task failed',
  },
  cancelled: {
    icon: <X className="h-3.5 w-3.5" />,
    className: 'text-slate-500',
    title: 'Task cancelled',
  },
}

export function getTaskStatusCardConfig(
  status: TaskStatus,
): TaskStatusCardConfig {
  return taskStatusCardConfig[status] || taskStatusCardConfig.pending
}

// ============================================================================
// Type Config (LucideIcon components, used by TaskListRow)
// ============================================================================

export const typeConfig: Record<
  TaskType,
  { icon: LucideIcon; label: string; className: string }
> = {
  feature: {
    icon: Package,
    label: 'Feature',
    className: 'text-purple-400',
  },
  bug: {
    icon: Bug,
    label: 'Bug',
    className: 'text-rose-400',
  },
  task: {
    icon: CheckSquare,
    label: 'Task',
    className: 'text-blue-400',
  },
  refactor: {
    icon: RefreshCw,
    label: 'Refactor',
    className: 'text-phosphor-400',
  },
  debt: {
    icon: AlertTriangle,
    label: 'Tech Debt',
    className: 'text-amber-400',
  },
  regression: {
    icon: ArrowDownCircle,
    label: 'Regression',
    className: 'text-orange-400',
  },
}

// ============================================================================
// Status Icon Config (LucideIcon components, used by TaskRow/TaskListRow)
// ============================================================================

export const statusIconConfig: Record<
  TaskStatus,
  { icon: LucideIcon; className: string; label: string }
> = {
  pending: {
    icon: Clock,
    className: 'text-slate-400',
    label: 'Pending',
  },
  running: {
    icon: Play,
    className: 'text-blue-400',
    label: 'Running',
  },
  completed: {
    icon: CheckCircle2,
    className: 'text-green-400',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    className: 'text-rose-400',
    label: 'Failed',
  },
  cancelled: {
    icon: XCircle,
    className: 'text-slate-500',
    label: 'Cancelled',
  },
}

// ============================================================================
// Type Icons (legacy, used by ReadyWorkSection/TaskRow)
// ============================================================================

export const typeIcons: Record<string, LucideIcon> = {
  feature: Package,
  bug: Bug,
  task: ListTodo,
}
