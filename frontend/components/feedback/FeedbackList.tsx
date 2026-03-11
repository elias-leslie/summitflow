'use client'

import { clsx } from 'clsx'
import { Loader2, MessageSquare, ThumbsUp } from 'lucide-react'
import type { FeedbackItem, FeedbackFilters } from '@/lib/api/feedback'
import { formatTimeAgo } from '@/lib/format'
import { TYPE_CONFIG, STATUS_CONFIG } from './feedbackConstants'

// ============================================================================
// Types
// ============================================================================

interface FeedbackListProps {
  items: FeedbackItem[]
  isLoading: boolean
  filters: FeedbackFilters
  onItemClick: (id: string) => void
  selectedId: string | null
}

// ============================================================================
// Component
// ============================================================================

export function FeedbackList({
  items,
  isLoading,
  filters,
  onItemClick,
  selectedId,
}: FeedbackListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    )
  }

  if (items.length === 0) {
    return (
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
    )
  }

  return (
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
            <div className={clsx('flex-shrink-0 p-1.5 rounded', typeConf.bg)}>
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
                'flex-shrink-0 text-2xs px-2 py-0.5 rounded border',
                statusConf.bg,
                statusConf.color,
                statusConf.border,
              )}
            >
              {statusConf.label}
            </span>

            {/* Age */}
            <span className="flex-shrink-0 text-2xs text-slate-600 w-8 text-right">
              {formatTimeAgo(item.created_at)}
            </span>
          </button>
        )
      })}
    </div>
  )
}
