'use client'

import { clsx } from 'clsx'
import { Search } from 'lucide-react'
import type { FeedbackFilters, FeedbackStatusFilter } from '@/lib/api/feedback'
import { TYPE_CONFIG, COMPONENT_GROUPS, SORT_OPTIONS } from './feedbackConstants'

// ============================================================================
// Types
// ============================================================================

interface FeedbackFilterBarProps {
  filters: FeedbackFilters
  onFiltersChange: (filters: Partial<FeedbackFilters>) => void
  total: number
  searchInput: string
  onSearchInputChange: (value: string) => void
  onSearchSubmit: (e: React.FormEvent) => void
}

// ============================================================================
// Component
// ============================================================================

export function FeedbackFilterBar({
  filters,
  onFiltersChange,
  total,
  searchInput,
  onSearchInputChange,
  onSearchSubmit,
}: FeedbackFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Search */}
      <form onSubmit={onSearchSubmit} className="flex-1 min-w-[200px] max-w-md">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => onSearchInputChange(e.target.value)}
            placeholder="Search feedback..."
            className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg
                       text-sm text-slate-200 placeholder-slate-500
                       focus:outline-none focus:border-outrun-500/40 focus:ring-1 focus:ring-outrun-500/20
                       transition-all"
          />
        </div>
      </form>

      {/* Type pills */}
      <div className="flex items-center gap-1.5">
        {(Object.entries(TYPE_CONFIG) as [keyof typeof TYPE_CONFIG, (typeof TYPE_CONFIG)[keyof typeof TYPE_CONFIG]][]).map(
          ([type, config]) => {
            const Icon = config.icon
            const isActive = filters.feedback_type === type
            return (
              <button
                type="button"
                key={type}
                onClick={() =>
                  onFiltersChange({
                    feedback_type: isActive ? undefined : type,
                  })
                }
                className={clsx(
                  'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all',
                  isActive
                    ? `${config.bg} ${config.color} ${config.border} border`
                    : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/50',
                )}
              >
                <Icon className="w-3 h-3" />
                {config.label}
              </button>
            )
          },
        )}
      </div>

      {/* Status */}
      <select
        value={filters.status || ''}
        onChange={(e) =>
          onFiltersChange({
            status: (e.target.value || undefined) as FeedbackStatusFilter | undefined,
          })
        }
        className="px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg
                   text-xs text-slate-300 focus:outline-none focus:border-outrun-500/40"
      >
        <option value="">All Status</option>
        <option value="active">Active</option>
        <option value="open">Open</option>
        <option value="acknowledged">Acknowledged</option>
        <option value="resolved">Resolved</option>
        <option value="wont_fix">Won&apos;t Fix</option>
        <option value="archived">Archived</option>
      </select>

      {/* Component */}
      <select
        value={filters.component_id || ''}
        onChange={(e) =>
          onFiltersChange({ component_id: e.target.value || undefined })
        }
        className="px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg
                   text-xs text-slate-300 focus:outline-none focus:border-outrun-500/40"
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
        className="px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg
                   text-xs text-slate-300 focus:outline-none focus:border-outrun-500/40"
      >
        {SORT_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <span className="text-xs text-slate-500 ml-auto">
        {total} item{total !== 1 ? 's' : ''}
      </span>
    </div>
  )
}
