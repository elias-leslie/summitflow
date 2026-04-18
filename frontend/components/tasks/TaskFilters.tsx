'use client'

import { Filter } from 'lucide-react'
import type { TaskStatus, TaskType } from '@/lib/api'
import { statusIconConfig } from '@/lib/task-config'
import { cn } from '@/lib/utils'

export interface TaskFilterValues {
  type: TaskType | 'all'
  status: TaskStatus | 'all'
  priority: number | 'all'
}

interface TaskFiltersProps {
  projectId: string
  filters: TaskFilterValues
  onChange: (filters: TaskFilterValues) => void
  className?: string
}

const STATUS_OPTIONS: { value: TaskStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All Statuses' },
  ...Object.entries(statusIconConfig).map(([value, config]) => ({
    value: value as TaskStatus,
    label: config.label,
  })),
]

const TYPE_OPTIONS = [
  { value: 'all', label: 'All Types' },
  { value: 'feature', label: 'Features' },
  { value: 'bug', label: 'Bugs' },
  { value: 'task', label: 'Tasks' },
  { value: 'refactor', label: 'Refactors' },
  { value: 'debt', label: 'Tech Debt' },
  { value: 'regression', label: 'Regressions' },
]

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
