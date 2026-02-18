/**
 * Task type and status configuration with React icon nodes.
 */

import {
  AlertTriangle,
  ArrowDownCircle,
  Bot,
  Bug,
  Check,
  CheckCircle2,
  CheckSquare,
  Clock,
  ListTodo,
  Loader2,
  OctagonX,
  Package,
  Pause,
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
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  task: {
    icon: <CheckSquare className="h-4 w-4" />,
    label: 'Task',
    className: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  },
  refactor: {
    icon: <RefreshCw className="h-4 w-4" />,
    label: 'Refactor',
    className: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
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
    className: 'text-red-400',
  },
  task: {
    icon: <CheckSquare className="h-3.5 w-3.5" />,
    className: 'text-blue-400',
  },
  refactor: {
    icon: <RefreshCw className="h-3.5 w-3.5" />,
    className: 'text-cyan-400',
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
  queue: {
    icon: <Clock className="h-3.5 w-3.5" />,
    className: 'text-sky-400',
    title: 'Queued for execution',
  },
  running: {
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    className: 'text-blue-400',
    title: 'Task running',
  },
  paused: {
    icon: <Pause className="h-3.5 w-3.5" />,
    className: 'text-yellow-400',
    title: 'Task paused',
  },
  blocked: {
    icon: <OctagonX className="h-3.5 w-3.5" />,
    className: 'text-orange-400',
    title: 'Task blocked',
  },
  ai_reviewing: {
    icon: <Bot className="h-3.5 w-3.5 animate-pulse" />,
    className: 'text-amber-400',
    title: 'AI reviewing',
  },
  completed: {
    icon: <Check className="h-3.5 w-3.5" />,
    className: 'text-green-400',
    title: 'Task completed',
  },
  failed: {
    icon: <X className="h-3.5 w-3.5" />,
    className: 'text-red-400',
    title: 'Task failed',
  },
  cancelled: {
    icon: <X className="h-3.5 w-3.5" />,
    className: 'text-slate-500',
    title: 'Task cancelled',
  },
  abandoned: {
    icon: <X className="h-3.5 w-3.5" />,
    className: 'text-slate-500',
    title: 'Task abandoned',
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
    className: 'text-cyan-400',
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
  queue: {
    icon: Clock,
    className: 'text-sky-400',
    label: 'Queue',
  },
  running: {
    icon: Play,
    className: 'text-blue-400',
    label: 'Running',
  },
  paused: {
    icon: Pause,
    className: 'text-amber-400',
    label: 'Paused',
  },
  blocked: {
    icon: OctagonX,
    className: 'text-orange-400',
    label: 'Blocked',
  },
  ai_reviewing: {
    icon: Bot,
    className: 'text-amber-400',
    label: 'AI Reviewing',
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
  abandoned: {
    icon: XCircle,
    className: 'text-slate-500',
    label: 'Abandoned',
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
