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
    <div className="flex flex-wrap items-center gap-1 rounded-full border border-slate-700/70 bg-slate-950/70 p-1">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value === '' ? undefined : (opt.value as T))}
          aria-pressed={(value ?? '') === opt.value}
          className={clsx(
            'rounded-full px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] transition-all',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500/40',
            (value ?? '') === opt.value
              ? 'bg-slate-700 text-slate-100 shadow-inner'
              : 'text-slate-500 hover:bg-slate-800/50 hover:text-slate-300',
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
    <div className="card-elevated px-3 py-3">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end">
        <form
          onSubmit={onSearchSubmit}
          className="min-w-[220px] flex-1 xl:max-w-sm"
        >
          <label className="block text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Search
          </label>
        <div className="relative">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => onSearchInputChange(e.target.value)}
              placeholder="Search titles, components, or agents"
              className="mt-2 w-full rounded-[1rem] border border-slate-700/70 bg-slate-950/70 py-2.5 pl-9 pr-3 text-sm text-slate-200 placeholder-slate-500 transition-all focus:outline-none focus:ring-1 focus:ring-phosphor-500"
          />
        </div>
        </form>

        <div className="grid flex-1 gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_180px_180px_auto]">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
              Type
            </div>
            <div className="mt-2">
              <SegmentedToggle
                options={typeOptions}
                value={filters.feedback_type}
                onChange={(v) => onFiltersChange({ feedback_type: v })}
              />
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
              Status
            </div>
            <div className="mt-2">
              <SegmentedToggle
                options={statusOptions}
                value={filters.status}
                onChange={(v) =>
                  onFiltersChange({ status: v as FeedbackStatusFilter | undefined })
                }
              />
            </div>
          </div>

          <label className="block text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Component
            <select
              value={filters.component_id || ''}
              onChange={(e) =>
                onFiltersChange({ component_id: e.target.value || undefined })
              }
              aria-label="Filter by component"
              className="mt-2 w-full rounded-[1rem] border border-slate-700/70 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-200 transition-colors focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20"
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
          </label>

          <label className="block text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Sort
            <select
              value={filters.sort || 'votes'}
              onChange={(e) =>
                onFiltersChange({
                  sort: e.target.value as FeedbackFilters['sort'],
                })
              }
              aria-label="Sort feedback"
              className="mt-2 w-full rounded-[1rem] border border-slate-700/70 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-200 transition-colors focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-end justify-end">
            <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-300">
              {total} item{total !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
