'use client'

import { Filter } from 'lucide-react'
import type { TaskStatus, TaskType } from '@/lib/api'
import { statusIconConfig } from '@/lib/task-config'
import { cn } from '@/lib/utils'

/**
 * The type sets the dashboard's Tasks and Bugs counts cover (mirrors the backend's
 * TASK_TILE_TYPES / BUG_TILE_TYPES).
 */
const TYPE_GROUPS = {
  'task,refactor': ['task', 'refactor'],
  'bug,regression': ['bug', 'regression'],
} as const satisfies Record<string, readonly TaskType[]>

type TaskTypeGroup = keyof typeof TYPE_GROUPS

export interface TaskFilterValues {
  type: TaskType | 'all' | TaskTypeGroup
  /**
   * 'blocked' matches open tasks waiting on an unfinished dependency and 'active' matches
   * open tasks (what the dashboard counts); neither is a stored status.
   */
  status: TaskStatus | 'all' | 'blocked' | 'active'
  priority: number | 'all'
}

interface TaskFiltersProps {
  projectId: string
  filters: TaskFilterValues
  onChange: (filters: TaskFilterValues) => void
  className?: string
}

const STATUS_OPTIONS: {
  value: TaskFilterValues['status']
  label: string
}[] = [
  { value: 'all', label: 'All Statuses' },
  { value: 'active', label: 'Open (not paused or done)' },
  ...Object.entries(statusIconConfig).map(([value, config]) => ({
    value: value as TaskStatus,
    label: config.label,
  })),
  { value: 'blocked', label: 'Blocked by a task' },
]

/** Statuses the dashboard's Features/Tasks/Bugs counts leave out (mirrors the backend's inactive set). */
const NOT_OPEN = new Set([
  'completed',
  'failed',
  'cancelled',
  'abandoned',
  'closed',
  'paused',
])

export function isOpenTask(status: string): boolean {
  return !NOT_OPEN.has(status)
}

/** A status filter a link may carry in ?status=. */
export function isStatusFilter(
  value: string | null,
): value is TaskFilterValues['status'] {
  return STATUS_OPTIONS.some((option) => option.value === value)
}

const TYPE_OPTIONS: { value: TaskFilterValues['type']; label: string }[] = [
  { value: 'all', label: 'All Types' },
  { value: 'feature', label: 'Features' },
  { value: 'bug', label: 'Bugs' },
  { value: 'task', label: 'Tasks' },
  { value: 'refactor', label: 'Refactors' },
  { value: 'debt', label: 'Tech Debt' },
  { value: 'regression', label: 'Regressions' },
  { value: 'task,refactor', label: 'Tasks and refactors' },
  { value: 'bug,regression', label: 'Bugs and regressions' },
]

/** A type filter a link may carry in ?taskType=. */
export function isTypeFilter(
  value: string | null,
): value is TaskFilterValues['type'] {
  return TYPE_OPTIONS.some((option) => option.value === value)
}

export function matchesTypeFilter(
  filter: TaskFilterValues['type'],
  taskType: TaskType | undefined,
): boolean {
  if (filter === 'all') return true
  if (filter in TYPE_GROUPS) {
    const group: readonly string[] = TYPE_GROUPS[filter as TaskTypeGroup]
    return taskType !== undefined && group.includes(taskType)
  }
  return taskType === filter
}

const PRIORITY_OPTIONS = [
  { value: 'all', label: 'All Priority' },
  { value: 0, label: 'P0 - Critical' },
  { value: 1, label: 'P1 - High' },
  { value: 2, label: 'P2 - Medium' },
  { value: 3, label: 'P3 - Low' },
  { value: 4, label: 'P4 - Backlog' },
]

export function TaskFilters({
  filters,
  onChange,
  className,
}: TaskFiltersProps) {
  const handleChange = (
    key: keyof TaskFilterValues,
    value: string | number | boolean,
  ) => {
    onChange({ ...filters, [key]: value })
  }

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <Filter className="w-4 h-4 text-slate-500" />

      {/* Type Filter */}
      <select
        value={filters.type}
        onChange={(e) => handleChange('type', e.target.value)}
        aria-label="Filter by task type"
        className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
      >
        {TYPE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Status Filter */}
      <select
        value={filters.status}
        onChange={(e) => handleChange('status', e.target.value)}
        aria-label="Filter by status"
        className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Priority Filter */}
      <select
        value={filters.priority}
        onChange={(e) => {
          const val = e.target.value
          handleChange('priority', val === 'all' ? 'all' : parseInt(val, 10))
        }}
        aria-label="Filter by priority"
        className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
      >
        {PRIORITY_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export const DEFAULT_FILTERS: TaskFilterValues = {
  type: 'all',
  status: 'all',
  priority: 'all',
}

const STORAGE_KEY = 'summitflow-task-filters'

export function loadFilters(): TaskFilterValues {
  if (typeof window === 'undefined') return DEFAULT_FILTERS
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      return { ...DEFAULT_FILTERS, ...parsed }
    }
  } catch {
    // Ignore parse errors
  }
  return DEFAULT_FILTERS
}

export function saveFilters(filters: TaskFilterValues): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filters))
  } catch {
    // Ignore storage errors
  }
}
