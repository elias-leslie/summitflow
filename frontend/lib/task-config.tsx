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
  Database,
  FileCode,
  GitPullRequest,
  Layout,
  ListTodo,
  Loader2,
  OctagonX,
  Package,
  Pause,
  Play,
  RefreshCw,
  Search,
  Server,
  TestTube,
  X,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
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

// ============================================================================
// Priority Config (label + color variant, used by TaskRow/TaskListRow)
// ============================================================================

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

// ============================================================================
// Kanban Label Mapping (status → column name)
// ============================================================================

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

// ============================================================================
// Type Icons (legacy, used by ReadyWorkSection/TaskRow)
// ============================================================================

export const typeIcons: Record<string, LucideIcon> = {
  feature: Package,
  bug: Bug,
  task: ListTodo,
}

// ============================================================================
// Date Formatting
// ============================================================================

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

// ============================================================================
// Phase Configuration (subtask phases)
// ============================================================================

export interface PhaseConfig {
  icon: LucideIcon
  color: string
  bgColor: string
}

export const PHASE_CONFIG: Record<string, PhaseConfig> = {
  research: {
    icon: Search,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
  },
  database: {
    icon: Database,
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
  },
  backend: {
    icon: Server,
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
  },
  frontend: {
    icon: Layout,
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/10',
  },
  testing: {
    icon: TestTube,
    color: 'text-rose-400',
    bgColor: 'bg-rose-500/10',
  },
  other: {
    icon: FileCode,
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/10',
  },
}

export const PHASE_ICONS: Record<string, LucideIcon> = Object.fromEntries(
  Object.entries(PHASE_CONFIG).map(([k, v]) => [k, v.icon]),
)

export const PHASE_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(PHASE_CONFIG).map(([k, v]) => [k, `${v.color} ${v.bgColor}`]),
)

export function getPhaseConfig(phase: string): PhaseConfig {
  return PHASE_CONFIG[phase] || PHASE_CONFIG.other
}

// ============================================================================
// Priority Detail Config (label + shortLabel + color, used by TaskPreview)
// ============================================================================

export interface PriorityDetailConfig {
  label: string
  shortLabel: string
  color: string
}

export const PRIORITY_CONFIG: Record<number, PriorityDetailConfig> = {
  0: { label: 'P0 Critical', shortLabel: 'P0', color: 'text-red-400' },
  1: { label: 'P1 High', shortLabel: 'P1', color: 'text-orange-400' },
  2: { label: 'P2 Medium', shortLabel: 'P2', color: 'text-yellow-400' },
  3: { label: 'P3 Low', shortLabel: 'P3', color: 'text-slate-400' },
  4: { label: 'P4 Backlog', shortLabel: 'P4', color: 'text-slate-500' },
}

export function getPriorityConfig(priority: number): PriorityDetailConfig {
  return PRIORITY_CONFIG[priority] || PRIORITY_CONFIG[2]
}

// ============================================================================
// Category Colors (for acceptance criteria)
// ============================================================================

export const CATEGORY_COLORS: Record<string, string> = {
  performance: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  correctness: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  security: 'text-red-400 bg-red-500/10 border-red-500/20',
  quality: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
}

export function getCategoryColor(category: string): string {
  return (
    CATEGORY_COLORS[category] ||
    'text-slate-400 bg-slate-500/10 border-slate-500/20'
  )
}
