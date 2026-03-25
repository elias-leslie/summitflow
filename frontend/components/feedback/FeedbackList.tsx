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
import { type ReactNode, useState } from 'react'
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
import { STATUS_CONFIG, TYPE_CONFIG } from './feedbackConstants'

const TYPE_ACCENT: Record<string, string> = {
  friction: 'border-l-red-500',
  idea: 'border-l-amber-500',
  improvement: 'border-l-blue-500',
  praise: 'border-l-emerald-500',
}

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  wont_fix: "Won't Fix",
  archived: 'Archived',
}

function DetailCard({
  label,
  value,
}: {
  label: string
  value: ReactNode
}) {
  return (
    <div className="min-w-0 rounded-[1rem] border border-slate-800/70 bg-slate-950/55 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div className="mt-1 min-w-0 truncate text-xs text-slate-200">{value}</div>
    </div>
  )
}

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
      <div className="flex items-center gap-2 px-5 py-6 text-xs text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading details...
      </div>
    )
  }

  if (!item) return null

  const pillClass =
    'flex items-center gap-1 rounded-full border px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] transition-colors disabled:opacity-40'

  return (
    <div className="space-y-3 border-t border-slate-800/40 bg-slate-950/30 px-4 py-3">
      {item.description ? (
        <div className="rounded-[1.15rem] border border-slate-800/70 bg-slate-950/55 px-4 py-4">
          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Description
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
            {item.description}
          </p>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <DetailCard
          label="Status"
          value={STATUS_LABELS[item.status] ?? item.status}
        />
        <DetailCard label="Votes" value={item.vote_count} />
        <DetailCard label="Project" value={item.project_id} />
        <DetailCard label="Created" value={formatShortDate(item.created_at)} />
        {item.agent_slug ? <DetailCard label="Agent" value={item.agent_slug} /> : null}
        {item.model_used ? <DetailCard label="Model" value={item.model_used} /> : null}
        {item.severity ? <DetailCard label="Severity" value={item.severity} /> : null}
        {item.linked_task_id ? (
          <DetailCard
            label="Linked Task"
            value={
              <span className="flex items-center gap-1">
                <span className="truncate font-mono text-phosphor-400">
                  {item.linked_task_id}
                </span>
                <ExternalLink className="h-3 w-3 shrink-0 text-phosphor-500" />
              </span>
            }
          />
        ) : null}
      </div>

      {item.resolution_note ? (
        <div className="rounded-[1.15rem] border border-emerald-500/20 bg-emerald-500/8 p-4">
          <div className="mb-1 text-[10px] uppercase tracking-[0.14em] text-emerald-400">
            Resolution
          </div>
          <p className="text-xs text-slate-300">{item.resolution_note}</p>
          {item.resolved_at ? (
            <p className="mt-1 text-2xs text-slate-500">
              {formatShortDate(item.resolved_at)}
            </p>
          ) : null}
        </div>
      ) : null}

      {item.votes && item.votes.length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <ThumbsUp className="h-3 w-3" />
            {item.votes.length} vote{item.votes.length !== 1 ? 's' : ''}
          </div>
          <div className="space-y-2">
            {item.votes.map((vote) => (
              <div
                key={vote.id}
                className="flex items-start gap-2 rounded-[1rem] border border-slate-800/70 bg-slate-950/50 px-3 py-2.5"
              >
                <ThumbsUp className="mt-0.5 h-3 w-3 shrink-0 text-slate-600" />
                <div className="min-w-0 flex-1">
                  {vote.comment ? (
                    <p className="mb-0.5 text-xs text-slate-300">{vote.comment}</p>
                  ) : null}
                  <div className="flex items-center gap-2 text-2xs text-slate-600">
                    {vote.agent_slug ? <span>{vote.agent_slug}</span> : null}
                    <span>{formatShortDate(vote.created_at)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {item.status !== 'archived'
          ? showResolveInput
            ? (
                <div className="flex flex-1 items-center gap-2">
                  <input
                    type="text"
                    value={resolutionNote}
                    onChange={(e) => setResolutionNote(e.target.value)}
                    placeholder="Resolution note (optional)"
                    className="flex-1 rounded-[1rem] border border-slate-700/70 bg-slate-950/70 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                  />
                  <button
                    type="button"
                    onClick={handleResolveConfirm}
                    disabled={statusMutation.isPending}
                    className={clsx(
                      pillClass,
                      'border-emerald-500/20 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20',
                    )}
                  >
                    {statusMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Check className="h-3 w-3" />
                    )}
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowResolveInput(false)}
                    className="px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-500 transition-colors hover:text-slate-300"
                  >
                    Cancel
                  </button>
                </div>
              )
            : (
                <>
                  {item.status === 'open' || item.status === 'acknowledged' ? (
                    <>
                      {item.status === 'open' ? (
                        <button
                          type="button"
                          onClick={() =>
                            statusMutation.mutate({ status: 'acknowledged' })
                          }
                          disabled={statusMutation.isPending}
                          className={clsx(
                            pillClass,
                            'border-amber-500/20 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20',
                          )}
                        >
                          <Clock className="h-3 w-3" />
                          Acknowledge
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setShowResolveInput(true)}
                        disabled={statusMutation.isPending}
                        className={clsx(
                          pillClass,
                          'border-emerald-500/20 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20',
                        )}
                      >
                        <Check className="h-3 w-3" />
                        Resolve
                      </button>
                      <button
                        type="button"
                        onClick={() => statusMutation.mutate({ status: 'wont_fix' })}
                        disabled={statusMutation.isPending}
                        className="px-2 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-500 transition-colors hover:text-slate-400 disabled:opacity-40"
                      >
                        Won&apos;t Fix
                      </button>
                    </>
                  ) : null}
                  {item.status === 'resolved' || item.status === 'wont_fix' ? (
                    <button
                      type="button"
                      onClick={() => statusMutation.mutate({ status: 'archived' })}
                      disabled={statusMutation.isPending}
                      className={clsx(
                        pillClass,
                        'border-slate-700/70 bg-slate-700/40 text-slate-300 hover:bg-slate-700/60',
                      )}
                    >
                      Archive
                    </button>
                  ) : null}
                </>
              )
          : null}

        <button
          type="button"
          onClick={() => setShowDeleteConfirm(true)}
          disabled={deleteMutation.isPending}
          className="ml-auto flex items-center gap-1 rounded-full border border-rose-500/15 px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] text-rose-300/70 transition-colors hover:bg-rose-500/10 hover:text-rose-300 disabled:opacity-40"
        >
          {deleteMutation.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Trash2 className="h-3 w-3" />
          )}
          Delete
        </button>
      </div>

      {showDeleteConfirm ? (
        <ConfirmDeleteDialog
          entityType="feedback"
          entityName={item.title}
          isDeleting={deleteMutation.isPending}
          isError={deleteMutation.isError}
          onConfirm={() => deleteMutation.mutate()}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      ) : null}
    </div>
  )
}

interface FeedbackListProps {
  items: FeedbackItem[]
  isLoading: boolean
  filters: FeedbackFilters
  onItemClick: (id: string | null) => void
  selectedId: string | null
}

export function FeedbackList({
  items,
  isLoading,
  filters,
  onItemClick,
  selectedId,
}: FeedbackListProps) {
  if (isLoading) {
    return (
      <div className="card-elevated flex items-center justify-center py-20">
        <div className="flex items-center gap-2.5 text-sm text-slate-500">
          <RefreshCw className="h-5 w-5 animate-spin text-phosphor-500" />
          Loading feedback...
        </div>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="card-elevated py-20 text-center text-slate-500">
        <MessageSquare className="mx-auto mb-3 h-8 w-8 opacity-40" />
        <p className="text-sm text-slate-300">
          {filters.query || filters.feedback_type || filters.component_id
            ? 'No feedback matches filters'
            : 'No feedback yet'}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Adjust the current filters or wait for the next agent report.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const typeConf = TYPE_CONFIG[item.feedback_type]
        const statusConf = STATUS_CONFIG[item.status]
        const TypeIcon = typeConf.icon
        const accentClass = TYPE_ACCENT[item.feedback_type] ?? 'border-l-slate-600'
        const isExpanded = selectedId === item.id

        return (
          <div
            key={item.id}
            className={clsx(
              'overflow-hidden rounded-xl border-l-[3px] border border-slate-700/60 bg-slate-950/45 transition-all duration-200',
              accentClass,
              isExpanded
                ? 'border-slate-700/80 shadow-[0_24px_60px_rgba(2,6,23,0.3)]'
                : 'hover:-translate-y-0.5 hover:bg-slate-900/55',
            )}
          >
            <div
              role="button"
              tabIndex={0}
              onClick={() => onItemClick(isExpanded ? null : item.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onItemClick(isExpanded ? null : item.id)
                }
              }}
              className="group cursor-pointer select-none px-4 py-3"
            >
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <ChevronRight
                    className={clsx(
                      'mt-1 h-3.5 w-3.5 shrink-0 text-slate-600 transition-all duration-200 group-hover:text-slate-400',
                      isExpanded && 'rotate-90',
                    )}
                  />

                  <div
                    className={clsx(
                      'mt-0.5 shrink-0 rounded-xl border p-2',
                      typeConf.bg,
                      typeConf.border,
                    )}
                  >
                    <TypeIcon className={clsx('h-3.5 w-3.5', typeConf.color)} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-base font-medium text-slate-100">
                        {item.title}
                      </span>
                      {item.severity ? (
                        <span
                          className={clsx(
                            'shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.16em]',
                            item.severity === 'high'
                              ? 'border-red-500/20 bg-red-500/10 text-red-300'
                              : item.severity === 'medium'
                                ? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
                                : 'border-slate-700/70 bg-slate-950/70 text-slate-400',
                          )}
                        >
                          {item.severity}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                        {typeConf.label}
                      </span>
                      <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-400">
                        {item.component_id}
                      </span>
                      {item.agent_slug ? (
                        <span className="text-[11px] text-slate-500">
                          {item.agent_slug}
                        </span>
                      ) : null}
                      <span className="text-[11px] text-slate-500">
                        {formatTimeAgo(item.created_at)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 md:ml-4">
                  {item.vote_count > 0 ? (
                    <div className="flex shrink-0 items-center gap-1 rounded-full border border-slate-600/40 bg-slate-700/40 px-2.5 py-1">
                      <ThumbsUp className="h-3 w-3 text-slate-400" />
                      <span className="font-mono text-xs font-medium tabular-nums text-slate-200">
                        {item.vote_count}
                      </span>
                    </div>
                  ) : null}

                  <span
                    className={clsx(
                      'shrink-0 rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-[0.16em]',
                      statusConf.bg,
                      statusConf.color,
                      statusConf.border,
                    )}
                  >
                    {statusConf.label}
                  </span>
                </div>
              </div>
            </div>

            <div
              className={clsx(
                'grid transition-all duration-200 ease-out',
                isExpanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
              )}
            >
              <div className="overflow-hidden">
                {isExpanded ? (
                  <InlineDetail
                    itemId={item.id}
                    onCollapse={() => onItemClick(null)}
                  />
                ) : null}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
