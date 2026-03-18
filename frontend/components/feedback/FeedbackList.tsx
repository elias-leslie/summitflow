'use client'

import { clsx } from 'clsx'
import { MessageSquare, RefreshCw, ThumbsUp } from 'lucide-react'
import type { FeedbackItem, FeedbackFilters } from '@/lib/api/feedback'
import { formatTimeAgo } from '@/lib/format'
import { TYPE_CONFIG, STATUS_CONFIG } from './feedbackConstants'

// ─── Accent colors by type ───────────────────────────────────────

const TYPE_ACCENT: Record<string, string> = {
  friction: 'border-l-red-500',
  idea: 'border-l-amber-500',
  improvement: 'border-l-blue-500',
  praise: 'border-l-emerald-500',
}

// ─── Types ───────────────────────────────────────────────────────

interface FeedbackListProps {
  items: FeedbackItem[]
  isLoading: boolean
  filters: FeedbackFilters
  onItemClick: (id: string) => void
  selectedId: string | null
}

// ─── Component ───────────────────────────────────────────────────

export function FeedbackList({
  items,
  isLoading,
  filters,
  onItemClick,
  selectedId,
}: FeedbackListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="flex items-center gap-2.5 text-slate-500 text-sm">
          <RefreshCw className="w-5 h-5 animate-spin text-phosphor-500" />
          Loading feedback...
        </div>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="text-center py-20 text-slate-600">
        <MessageSquare className="w-8 h-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">
          {filters.query || filters.feedback_type || filters.component_id
            ? 'No feedback matches filters'
            : 'No feedback yet'}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {items.map((item) => {
        const typeConf = TYPE_CONFIG[item.feedback_type]
        const statusConf = STATUS_CONFIG[item.status]
        const TypeIcon = typeConf.icon
        const accentClass = TYPE_ACCENT[item.feedback_type] ?? 'border-l-slate-600'
        const isSelected = selectedId === item.id

        return (
          <button
            type="button"
            key={item.id}
            onClick={() => onItemClick(item.id)}
            className={clsx(
              'w-full rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 px-4 py-3 text-left transition-all duration-200',
              accentClass,
              isSelected
                ? 'border-slate-700/80 shadow-lg shadow-black/20 bg-slate-800/60'
                : 'hover:bg-slate-800/60',
            )}
          >
            <div className="flex items-start gap-3">
              {/* Type icon */}
              <div
                className={clsx(
                  'mt-0.5 shrink-0 rounded p-1.5',
                  typeConf.bg,
                )}
              >
                <TypeIcon className={clsx('h-3 w-3', typeConf.color)} />
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white truncate">
                    {item.title}
                  </span>
                  {item.severity && (
                    <span
                      className={clsx(
                        'shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] border',
                        item.severity === 'high'
                          ? 'bg-red-500/10 text-red-400 border-red-500/20'
                          : item.severity === 'medium'
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                            : 'bg-slate-700/50 text-slate-400 border-slate-600/40',
                      )}
                    >
                      {item.severity}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="rounded bg-slate-700/70 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">
                    {item.component_id}
                  </span>
                  {item.agent_slug && (
                    <span className="text-[11px] text-slate-600">
                      {item.agent_slug}
                    </span>
                  )}
                  <span className="text-[11px] text-slate-600">
                    {formatTimeAgo(item.created_at)}
                  </span>
                </div>
              </div>

              {/* Vote pill */}
              {item.vote_count > 0 && (
                <div className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-700/50 border border-slate-600/40">
                  <ThumbsUp className="w-3 h-3 text-slate-400" />
                  <span className="text-xs font-mono font-medium text-slate-300 tabular-nums">
                    {item.vote_count}
                  </span>
                </div>
              )}

              {/* Status badge */}
              <span
                className={clsx(
                  'shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] border',
                  statusConf.bg,
                  statusConf.color,
                  statusConf.border,
                )}
              >
                {statusConf.label}
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
