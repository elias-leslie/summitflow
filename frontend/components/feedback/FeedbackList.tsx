'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Check,
  ChevronRight,
  Clock,
  ExternalLink,
  Loader2,
  MessageSquare,
  RefreshCw,
  ThumbsUp,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import type { FeedbackFilters, FeedbackStatus } from '@/lib/api/feedback'
import {
  type FeedbackItem,
  deleteFeedbackItem,
  fetchFeedbackItem,
  updateFeedbackStatus,
} from '@/lib/api/feedback'
import { formatShortDate, formatTimeAgo } from '@/lib/format'
import { TYPE_CONFIG, STATUS_CONFIG } from './feedbackConstants'

// ─── Accent colors by type ───────────────────────────────────────

const TYPE_ACCENT: Record<string, string> = {
  friction: 'border-l-red-500',
  idea: 'border-l-amber-500',
  improvement: 'border-l-blue-500',
  praise: 'border-l-emerald-500',
}

// ─── Status Labels ───────────────────────────────────────────────

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  wont_fix: "Won't Fix",
  archived: 'Archived',
}

// ─── Inline Detail Expansion ─────────────────────────────────────

function InlineDetail({
  itemId,
  onCollapse,
}: {
  itemId: string
  onCollapse: () => void
}) {
  const queryClient = useQueryClient()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [resolutionNote, setResolutionNote] = useState('')
  const [showResolveInput, setShowResolveInput] = useState(false)

  const { data: item, isLoading } = useQuery({
    queryKey: ['feedback-item', itemId],
    queryFn: () => fetchFeedbackItem(itemId),
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['feedback-item', itemId] })
    queryClient.invalidateQueries({ queryKey: ['feedback-items'] })
    queryClient.invalidateQueries({ queryKey: ['feedback-summary'] })
  }

  const statusMutation = useMutation({
    mutationFn: (data: { status: FeedbackStatus; resolution_note?: string }) =>
      updateFeedbackStatus(itemId, data),
    onSuccess: () => {
      invalidateAll()
      toast.success('Feedback updated')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update feedback')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteFeedbackItem(itemId),
    onSuccess: () => {
      invalidateAll()
      toast.success('Feedback deleted')
      setShowDeleteConfirm(false)
      onCollapse()
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to delete feedback')
    },
  })

  const handleResolveConfirm = () => {
    statusMutation.mutate(
      { status: 'resolved', resolution_note: resolutionNote || undefined },
      {
        onSuccess: () => {
          setShowResolveInput(false)
          setResolutionNote('')
        },
      },
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-slate-500 text-xs">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Loading details...
      </div>
    )
  }

  if (!item) return null

  return (
    <div className="border-t border-slate-800/40 px-4 py-4 space-y-3">
      {/* Description */}
      {item.description && (
        <p className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">
          {item.description}
        </p>
      )}

      {/* Metadata grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Status
          </div>
          <div className="truncate text-xs text-slate-200 capitalize">
            {STATUS_LABELS[item.status] ?? item.status}
          </div>
        </div>
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Votes
          </div>
          <div className="truncate text-xs text-slate-200">
            {item.vote_count}
          </div>
        </div>
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Project
          </div>
          <div className="truncate text-xs text-slate-200">
            {item.project_id}
          </div>
        </div>
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Created
          </div>
          <div className="truncate text-xs text-slate-200">
            {formatShortDate(item.created_at)}
          </div>
        </div>
        {item.agent_slug && (
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Agent
            </div>
            <div className="truncate text-xs text-slate-200">
              {item.agent_slug}
            </div>
          </div>
        )}
        {item.model_used && (
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Model
            </div>
            <div className="truncate text-xs text-slate-200">
              {item.model_used}
            </div>
          </div>
        )}
        {item.severity && (
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Severity
            </div>
            <div className="truncate text-xs text-slate-200 capitalize">
              {item.severity}
            </div>
          </div>
        )}
        {item.linked_task_id && (
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Linked Task
            </div>
            <div className="flex items-center gap-1">
              <span className="truncate text-xs font-mono text-phosphor-400">
                {item.linked_task_id}
              </span>
              <ExternalLink className="w-3 h-3 text-phosphor-500 shrink-0" />
            </div>
          </div>
        )}
      </div>

      {/* Resolution note */}
      {item.resolution_note && (
        <div className="p-3 rounded-lg bg-emerald-500/8 border border-emerald-500/20">
          <div className="text-[10px] uppercase tracking-[0.14em] text-emerald-400 mb-1">
            Resolution
          </div>
          <p className="text-xs text-slate-300">{item.resolution_note}</p>
          {item.resolved_at && (
            <p className="text-2xs text-slate-500 mt-1">
              {formatShortDate(item.resolved_at)}
            </p>
          )}
        </div>
      )}

      {/* Votes */}
      {item.votes && item.votes.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500 mb-1.5 flex items-center gap-1.5">
            <ThumbsUp className="w-3 h-3" />
            {item.votes.length} vote{item.votes.length !== 1 ? 's' : ''}
          </div>
          <div className="space-y-1">
            {item.votes.map((vote) => (
              <div
                key={vote.id}
                className="rounded border border-slate-800/60 bg-slate-950/40 px-2.5 py-1.5 flex items-start gap-2"
              >
                <ThumbsUp className="w-3 h-3 text-slate-600 mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  {vote.comment && (
                    <p className="text-xs text-slate-300 mb-0.5">
                      {vote.comment}
                    </p>
                  )}
                  <div className="flex items-center gap-2 text-2xs text-slate-600">
                    {vote.agent_slug && <span>{vote.agent_slug}</span>}
                    <span>
                      {formatShortDate(vote.created_at)}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        {item.status !== 'archived' &&
          (showResolveInput ? (
              <div className="flex items-center gap-2 flex-1">
                <input
                  type="text"
                  value={resolutionNote}
                  onChange={(e) => setResolutionNote(e.target.value)}
                  placeholder="Resolution note (optional)"
                  className="flex-1 px-2 py-1 bg-slate-900/60 border border-slate-700/60 rounded
                             text-xs text-slate-200 placeholder-slate-500
                             focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                />
                <button
                  type="button"
                  onClick={handleResolveConfirm}
                  disabled={statusMutation.isPending}
                  className="text-2xs px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors flex items-center gap-1"
                >
                  {statusMutation.isPending ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Check className="w-3 h-3" />
                  )}
                  Confirm
                </button>
                <button
                  type="button"
                  onClick={() => setShowResolveInput(false)}
                  className="text-2xs px-2 py-1 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <>
                {(item.status === 'open' ||
                  item.status === 'acknowledged') && (
                  <>
                    {item.status === 'open' && (
                      <button
                        type="button"
                        onClick={() =>
                          statusMutation.mutate({ status: 'acknowledged' })
                        }
                        disabled={statusMutation.isPending}
                        className="text-2xs px-2 py-1 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-40 transition-colors flex items-center gap-1"
                      >
                        <Clock className="w-3 h-3" />
                        Acknowledge
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setShowResolveInput(true)}
                      disabled={statusMutation.isPending}
                      className="text-2xs px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors flex items-center gap-1"
                    >
                      <Check className="w-3 h-3" />
                      Resolve
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        statusMutation.mutate({ status: 'wont_fix' })
                      }
                      disabled={statusMutation.isPending}
                      className="text-2xs px-2 py-1 text-slate-500 hover:text-slate-400 disabled:opacity-40 transition-colors"
                    >
                      Won&apos;t Fix
                    </button>
                  </>
                )}
                {(item.status === 'resolved' ||
                  item.status === 'wont_fix') && (
                  <button
                    type="button"
                    onClick={() =>
                      statusMutation.mutate({ status: 'archived' })
                    }
                    disabled={statusMutation.isPending}
                    className="text-2xs px-2 py-1 rounded bg-slate-700/40 text-slate-400 hover:bg-slate-700/60 disabled:opacity-40 transition-colors"
                  >
                    Archive
                  </button>
                )}
              </>
            )
          )}

        <button
          type="button"
          onClick={() => setShowDeleteConfirm(true)}
          disabled={deleteMutation.isPending}
          className="text-2xs px-2 py-1 rounded text-red-500/60 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-40 transition-colors flex items-center gap-1 ml-auto"
        >
          {deleteMutation.isPending ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Trash2 className="w-3 h-3" />
          )}
          Delete
        </button>
      </div>

      {showDeleteConfirm && (
        <ConfirmDeleteDialog
          entityType="feedback"
          entityName={item.title}
          isDeleting={deleteMutation.isPending}
          isError={deleteMutation.isError}
          onConfirm={() => deleteMutation.mutate()}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}
    </div>
  )
}

// ─── Types ───────────────────────────────────────────────────────

interface FeedbackListProps {
  items: FeedbackItem[]
  isLoading: boolean
  filters: FeedbackFilters
  onItemClick: (id: string | null) => void
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
        const accentClass =
          TYPE_ACCENT[item.feedback_type] ?? 'border-l-slate-600'
        const isExpanded = selectedId === item.id

        return (
          <div
            key={item.id}
            className={clsx(
              'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 overflow-hidden transition-all duration-200',
              accentClass,
              isExpanded
                ? 'border-slate-700/80 shadow-lg shadow-black/20'
                : 'hover:bg-slate-800/60',
            )}
          >
            {/* Header row */}
            <div
              role="button"
              tabIndex={0}
              onClick={() => onItemClick(isExpanded ? null : item.id)}
              onKeyDown={(e) =>
                e.key === 'Enter' &&
                onItemClick(isExpanded ? null : item.id)
              }
              className="flex items-start gap-3 px-4 py-3 cursor-pointer select-none group"
            >
              <ChevronRight
                className={clsx(
                  'w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-all duration-200 shrink-0 mt-1',
                  isExpanded && 'rotate-90',
                )}
              />

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
                  <span className="text-sm text-slate-100 truncate">
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
                    <span className="text-2xs text-slate-600">
                      {item.agent_slug}
                    </span>
                  )}
                  <span className="text-2xs text-slate-600">
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

            {/* Expandable detail */}
            <div
              className={clsx(
                'grid transition-all duration-200 ease-out',
                isExpanded
                  ? 'grid-rows-[1fr] opacity-100'
                  : 'grid-rows-[0fr] opacity-0',
              )}
            >
              <div className="overflow-hidden">
                {isExpanded && (
                  <InlineDetail
                    itemId={item.id}
                    onCollapse={() => onItemClick(null)}
                  />
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
