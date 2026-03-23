'use client'

import { clsx } from 'clsx'
import { Search } from 'lucide-react'
import type { FeedbackFilters, FeedbackStatusFilter } from '@/lib/api/feedback'
import { TYPE_CONFIG, COMPONENT_GROUPS, SORT_OPTIONS } from './feedbackConstants'

// ─── Segmented Toggle ────────────────────────────────────────────

function SegmentedToggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T | ''; label: string }[]
  value: T | '' | undefined
  onChange: (value: T | undefined) => void
}) {
  return (
    <div className="flex rounded-md border border-slate-700/60 overflow-hidden">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value === '' ? undefined : (opt.value as T))}
          className={clsx(
            'px-2.5 py-1 text-2xs transition-colors',
            (value ?? '') === opt.value
              ? 'bg-slate-700 text-white'
              : 'bg-slate-900/50 text-slate-500 hover:text-slate-300',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

// ─── Main ────────────────────────────────────────────────────────

interface FeedbackFilterBarProps {
  filters: FeedbackFilters
  onFiltersChange: (filters: Partial<FeedbackFilters>) => void
  total: number
  searchInput: string
  onSearchInputChange: (value: string) => void
  onSearchSubmit: (e: React.FormEvent) => void
}

export function FeedbackFilterBar({
  filters,
  onFiltersChange,
  total,
  searchInput,
  onSearchInputChange,
  onSearchSubmit,
}: FeedbackFilterBarProps) {
  const typeOptions = [
    { value: '' as const, label: 'All' },
    ...Object.entries(TYPE_CONFIG).map(([key, conf]) => ({
      value: key,
      label: conf.label,
    })),
  ]

  const statusOptions: { value: FeedbackStatusFilter | ''; label: string }[] = [
    { value: '', label: 'All' },
    { value: 'active', label: 'Active' },
    { value: 'open', label: 'Open' },
    { value: 'acknowledged', label: 'Ack' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'wont_fix', label: "Won't Fix" },
    { value: 'archived', label: 'Archived' },
  ]

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Search */}
      <form onSubmit={onSearchSubmit} className="flex-1 min-w-[180px] max-w-sm">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => onSearchInputChange(e.target.value)}
            placeholder="Search..."
            className="w-full pl-8 pr-3 py-1.5 bg-slate-900/60 border border-slate-700/60 rounded-md
                       text-xs text-slate-200 placeholder-slate-500
                       focus:outline-none focus:ring-1 focus:ring-phosphor-500
                       transition-all"
          />
        </div>
      </form>

      {/* Type toggle */}
      <SegmentedToggle
        options={typeOptions}
        value={filters.feedback_type}
        onChange={(v) => onFiltersChange({ feedback_type: v })}
      />

      {/* Status toggle */}
      <SegmentedToggle
        options={statusOptions}
        value={filters.status}
        onChange={(v) => onFiltersChange({ status: v as FeedbackStatusFilter | undefined })}
      />

      {/* Component dropdown */}
      <select
        value={filters.component_id || ''}
        onChange={(e) =>
          onFiltersChange({ component_id: e.target.value || undefined })
        }
        className="px-2 py-1 bg-slate-900/60 border border-slate-700/60 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-phosphor-500"
      >
        <option value="">All Components</option>
        {Object.entries(COMPONENT_GROUPS).map(([group, components]) => (
          <optgroup key={group} label={group}>
            {components.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </optgroup>
        ))}
      </select>

      {/* Sort */}
      <select
        value={filters.sort || 'votes'}
        onChange={(e) =>
          onFiltersChange({
            sort: e.target.value as FeedbackFilters['sort'],
          })
        }
        className="px-2 py-1 bg-slate-900/60 border border-slate-700/60 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-phosphor-500"
      >
        {SORT_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <span className="text-2xs text-slate-500 ml-auto tabular-nums">
        {total} item{total !== 1 ? 's' : ''}
      </span>
    </div>
  )
}
