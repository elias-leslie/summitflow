/**
 * Task configuration - Priority, Status, and Type settings
 */

import {
  AlertTriangle,
  ArrowDownCircle,
  Bot,
  Bug,
  CheckCircle2,
  CheckSquare,
  Clock,
  GitPullRequest,
  ListTodo,
  OctagonX,
  Package,
  Pause,
  Play,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { TaskStatus, TaskType } from '@/lib/api'

// Priority colors and labels
export const priorityConfig: Record<
  number,
  { label: string; color: string; className: string }
> = {
  0: {
    label: 'P0',
    color: 'text-red-500',
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  1: {
    label: 'P1',
    color: 'text-orange-500',
    className: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  },
  2: {
    label: 'P2',
    color: 'text-yellow-500',
    className: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  3: {
    label: 'P3',
    color: 'text-blue-500',
    className: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  4: {
    label: 'P4',
    color: 'text-slate-500',
    className: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
}

// Type config - icon components, not elements
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

// Status config - icon components, not elements
export const statusConfig: Record<
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
  pr_created: {
    icon: GitPullRequest,
    className: 'text-amber-400',
    label: 'PR Created',
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
}

// Phase badge config - maps status to kanban column names
export const statusToKanbanLabel: Record<
  string,
  { label: string; className: string }
> = {
  pending: { label: 'Planning', className: 'bg-slate-600/50 text-slate-300' },
  running: {
    label: 'In Progress',
    className: 'bg-blue-600/50 text-blue-300',
  },
  paused: {
    label: 'In Progress',
    className: 'bg-amber-600/50 text-amber-300',
  },
  blocked: {
    label: 'In Progress',
    className: 'bg-orange-600/50 text-orange-300',
  },
  ai_reviewing: {
    label: 'AI Review',
    className: 'bg-cyan-600/50 text-cyan-300',
  },
  pr_created: {
    label: 'AI Review',
    className: 'bg-purple-600/50 text-purple-300',
  },
  completed: { label: 'Done', className: 'bg-green-600/50 text-green-300' },
  failed: { label: 'Done', className: 'bg-red-600/50 text-red-300' },
  cancelled: { label: 'Done', className: 'bg-slate-600/50 text-slate-300' },
}

// Type icons (legacy)
export const typeIcons: Record<string, LucideIcon> = {
  feature: Package,
  bug: Bug,
  task: ListTodo,
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffDays = Math.floor(
    (now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24),
  )

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
