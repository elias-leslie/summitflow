'use client'

import { clsx } from 'clsx'
import {
  Lightbulb,
  Loader2,
  MessageSquare,
  Search,
  Sparkles,
  ThumbsUp,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import type { FeedbackItem, FeedbackFilters } from '@/lib/api/feedback'

// ============================================================================
// Constants
// ============================================================================

const TYPE_CONFIG = {
  friction: {
    icon: Zap,
    label: 'Friction',
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
  },
  idea: {
    icon: Lightbulb,
    label: 'Idea',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  improvement: {
    icon: TrendingUp,
    label: 'Improvement',
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
  },
  praise: {
    icon: Sparkles,
    label: 'Praise',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
  },
} as const

const STATUS_CONFIG = {
  open: { label: 'Open', color: 'text-slate-300', bg: 'bg-slate-600/30', border: 'border-slate-500/30' },
  acknowledged: { label: 'Ack', color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30' },
  resolved: { label: 'Resolved', color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
  wont_fix: { label: "Won't Fix", color: 'text-slate-500', bg: 'bg-slate-700/30', border: 'border-slate-600/30' },
} as const

const SORT_OPTIONS = [
  { value: 'votes', label: 'Most Voted' },
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
] as const

const COMPONENT_GROUPS: Record<string, string[]> = {
  SummitFlow: ['sf.cli', 'sf.cli.memory', 'sf.dt', 'sf.quality', 'sf.worktree', 'sf.api', 'sf.storage', 'sf.workflows', 'sf.explorer', 'sf.frontend', 'sf.scripts'],
  'Agent Hub': ['ah.memory', 'ah.memory.tiers', 'ah.memory.continuity', 'ah.memory.citations', 'ah.memory.learning', 'ah.completion', 'ah.adapters', 'ah.sessions', 'ah.sdk', 'ah.orchestration', 'ah.hooks'],
  'Cross-Cutting': ['xc.tool_registry', 'xc.error_handling', 'xc.documentation', 'xc.testing'],
}

// ============================================================================
// Helper
// ============================================================================

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d`
  return `${Math.floor(days / 30)}mo`
}

// ============================================================================
// Components
// ============================================================================

interface FeedbackBoardProps {
  items: FeedbackItem[]
  total: number
  isLoading: boolean
  filters: FeedbackFilters
  onFiltersChange: (filters: Partial<FeedbackFilters>) => void
  onItemClick: (id: string) => void
  selectedId: string | null
}

export function FeedbackBoard({
  items,
  total,
  isLoading,
  filters,
  onFiltersChange,
  onItemClick,
  selectedId,
}: FeedbackBoardProps) {
  const [searchInput, setSearchInput] = useState(filters.query || '')

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    onFiltersChange({ query: searchInput || undefined })
  }

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <form onSubmit={handleSearch} className="flex-1 min-w-[200px] max-w-md">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
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
            onFiltersChange({ status: e.target.value || undefined })
          }
          className="px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg
                     text-xs text-slate-300 focus:outline-none focus:border-outrun-500/40"
        >
          <option value="">All Status</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="wont_fix">Won&apos;t Fix</option>
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

      {/* List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
        </div>
      ) : items.length === 0 ? (
        <div className="p-12 rounded-lg border border-slate-700/50 bg-slate-800/30 text-center">
          <MessageSquare className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <h3 className="text-sm font-medium text-slate-400 mb-1">
            No feedback found
          </h3>
          <p className="text-xs text-slate-500">
            {filters.query || filters.feedback_type || filters.component_id
              ? 'Try adjusting your filters'
              : 'Agents will report feedback as they work'}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-700/50 overflow-hidden divide-y divide-slate-800/50">
          {items.map((item) => {
            const typeConf = TYPE_CONFIG[item.feedback_type]
            const statusConf = STATUS_CONFIG[item.status]
            const TypeIcon = typeConf.icon

            return (
              <button
                key={item.id}
                onClick={() => onItemClick(item.id)}
                className={clsx(
                  'w-full flex items-center gap-4 px-4 py-3 text-left transition-all',
                  'hover:bg-slate-800/60',
                  selectedId === item.id
                    ? 'bg-slate-800/80 border-l-2 border-l-outrun-500'
                    : 'bg-slate-800/30',
                )}
              >
                {/* Type icon */}
                <div
                  className={clsx(
                    'flex-shrink-0 p-1.5 rounded',
                    typeConf.bg,
                  )}
                >
                  <TypeIcon className={clsx('w-3.5 h-3.5', typeConf.color)} />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-200 truncate">
                      {item.title}
                    </span>
                    {item.severity && (
                      <span
                        className={clsx(
                          'flex-shrink-0 text-2xs px-1.5 py-0.5 rounded',
                          item.severity === 'high'
                            ? 'bg-rose-500/10 text-rose-400'
                            : item.severity === 'medium'
                              ? 'bg-amber-500/10 text-amber-400'
                              : 'bg-slate-600/30 text-slate-400',
                        )}
                      >
                        {item.severity}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="mono text-2xs text-slate-500">
                      {item.component_id}
                    </span>
                    {item.agent_slug && (
                      <span className="text-2xs text-slate-600">
                        by {item.agent_slug}
                      </span>
                    )}
                  </div>
                </div>

                {/* Votes */}
                <div className="flex-shrink-0 flex items-center gap-1 text-slate-400">
                  <ThumbsUp className="w-3.5 h-3.5" />
                  <span className="text-xs font-medium">{item.vote_count}</span>
                </div>

                {/* Status */}
                <span
                  className={clsx(
                    'flex-shrink-0 text-2xs px-2 py-0.5 rounded',
                    statusConf.bg,
                    statusConf.color,
                    statusConf.border,
                    'border',
                  )}
                >
                  {statusConf.label}
                </span>

                {/* Age */}
                <span className="flex-shrink-0 text-2xs text-slate-600 w-8 text-right">
                  {timeAgo(item.created_at)}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
