/**
 * Shared task configuration for priority colors, task types, and status display.
 * Used across TaskModal, TaskCard, TaskDetailDrawer, and other task components.
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
  Eye,
  GitPullRequest,
  Loader2,
  OctagonX,
  Package,
  Pause,
  RefreshCw,
  X,
} from 'lucide-react'
import type { TaskStatus, TaskType } from '@/lib/api'

// ============================================================================
// Priority Colors
// ============================================================================

export interface PriorityColorConfig {
  bg: string
  text: string
  border: string
}

export const priorityColors: Record<number, PriorityColorConfig> = {
  0: {
    bg: 'bg-rose-500/30',
    text: 'text-rose-300',
    border: 'border-rose-500/40',
  },
  1: {
    bg: 'bg-orange-500/20',
    text: 'text-orange-400',
    border: 'border-orange-500/30',
  },
  2: {
    bg: 'bg-amber-500/20',
    text: 'text-amber-400',
    border: 'border-amber-500/30',
  },
  3: {
    bg: 'bg-blue-500/20',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
  },
  4: {
    bg: 'bg-slate-500/20',
    text: 'text-slate-400',
    border: 'border-slate-500/30',
  },
}

/** Combined class string for priority badges (TaskCard style) */
export const priorityColorClasses: Record<number, string> = {
  0: 'bg-rose-500/30 text-rose-300 border-rose-500/40', // Critical
  1: 'bg-orange-500/20 text-orange-400 border-orange-500/30', // High
  2: 'bg-amber-500/20 text-amber-400 border-amber-500/30', // Medium
  3: 'bg-blue-500/20 text-blue-400 border-blue-500/30', // Low
  4: 'bg-slate-500/20 text-slate-400 border-slate-500/30', // Backlog
}

export function getPriorityColors(priority: number): PriorityColorConfig {
  return priorityColors[priority] || priorityColors[2]
}

export function getPriorityClasses(priority: number): string {
  return priorityColorClasses[priority] || priorityColorClasses[2]
}

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
// Status Configuration
// ============================================================================

export interface StatusConfig {
  label: string
  className: string
  icon?: React.ReactNode
}

export const statusConfig: Record<TaskStatus, StatusConfig> = {
  pending: {
    label: 'Pending',
    className: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
  queue: {
    label: 'Queued',
    className: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
    icon: <Clock className="h-3 w-3" />,
  },
  running: {
    label: 'Running',
    className: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
  },
  paused: {
    label: 'Paused',
    className: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    icon: <Clock className="h-3 w-3" />,
  },
  blocked: {
    label: 'Blocked',
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  pr_created: {
    label: 'PR Created',
    className: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  },
  ai_reviewing: {
    label: 'AI Reviewing',
    className: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
  },
  human_review: {
    label: 'Human Review',
    className: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  completed: {
    label: 'Completed',
    className: 'bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30',
    icon: <CheckCircle2 className="h-3 w-3" />,
  },
  failed: {
    label: 'Failed',
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
}

export function getStatusConfig(status: TaskStatus): StatusConfig {
  return statusConfig[status] || statusConfig.pending
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
  pr_created: {
    icon: <GitPullRequest className="h-3.5 w-3.5" />,
    className: 'text-amber-400',
    title: 'PR created',
  },
  ai_reviewing: {
    icon: <Bot className="h-3.5 w-3.5 animate-pulse" />,
    className: 'text-amber-400',
    title: 'AI reviewing',
  },
  human_review: {
    icon: <Eye className="h-3.5 w-3.5" />,
    className: 'text-violet-400',
    title: 'Human review required',
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
}

export function getTaskStatusCardConfig(
  status: TaskStatus,
): TaskStatusCardConfig {
  return taskStatusCardConfig[status] || taskStatusCardConfig.pending
}
