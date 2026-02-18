'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Check,
  Clock,
  ExternalLink,
  Lightbulb,
  Loader2,
  Sparkles,
  ThumbsUp,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import {
  fetchFeedbackItem,
  updateFeedbackStatus,
} from '@/lib/api/feedback'

// ============================================================================
// Constants
// ============================================================================

const TYPE_CONFIG = {
  friction: { icon: Zap, label: 'Friction', color: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/30' },
  idea: { icon: Lightbulb, label: 'Idea', color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30' },
  improvement: { icon: TrendingUp, label: 'Improvement', color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30' },
  praise: { icon: Sparkles, label: 'Praise', color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
} as const

// ============================================================================
// Component
// ============================================================================

interface FeedbackDetailProps {
  itemId: string
  onClose: () => void
}

export function FeedbackDetail({ itemId, onClose }: FeedbackDetailProps) {
  const queryClient = useQueryClient()
  const [resolutionNote, setResolutionNote] = useState('')
  const [showResolveInput, setShowResolveInput] = useState(false)

  const { data: item, isLoading } = useQuery({
    queryKey: ['feedback-item', itemId],
    queryFn: () => fetchFeedbackItem(itemId),
  })

  const statusMutation = useMutation({
    mutationFn: (data: { status: string; resolution_note?: string }) =>
      updateFeedbackStatus(itemId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback-item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['feedback-items'] })
      queryClient.invalidateQueries({ queryKey: ['feedback-summary'] })
      setShowResolveInput(false)
      setResolutionNote('')
    },
  })

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    )
  }

  if (!item) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-slate-500">
        Feedback item not found
      </div>
    )
  }

  const typeConf = TYPE_CONFIG[item.feedback_type]
  const TypeIcon = typeConf.icon

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-slate-700/50">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={clsx(
                'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium',
                typeConf.bg,
                typeConf.color,
                typeConf.border,
                'border',
              )}
            >
              <TypeIcon className="w-3 h-3" />
              {typeConf.label}
            </span>
            <span className="mono text-xs text-slate-500">
              {item.component_id}
            </span>
          </div>
          <h2 className="text-lg font-semibold text-slate-100 leading-tight">
            {item.title}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="flex-shrink-0 p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        {/* Description */}
        {item.description && (
          <div>
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
              Description
            </h3>
            <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
              {item.description}
            </p>
          </div>
        )}

        {/* Metadata */}
        <div className="grid grid-cols-2 gap-3">
          <MetadataItem label="Status" value={item.status.replace('_', ' ')} />
          <MetadataItem label="Votes" value={String(item.vote_count)} />
          <MetadataItem label="Project" value={item.project_id} />
          <MetadataItem
            label="Created"
            value={new Date(item.created_at).toLocaleDateString()}
          />
          {item.agent_slug && (
            <MetadataItem label="Agent" value={item.agent_slug} />
          )}
          {item.model_used && (
            <MetadataItem label="Model" value={item.model_used} />
          )}
          {item.severity && (
            <MetadataItem label="Severity" value={item.severity} />
          )}
          {item.linked_task_id && (
            <div>
              <span className="text-2xs text-slate-500">Linked Task</span>
              <div className="flex items-center gap-1 mt-0.5">
                <span className="mono text-xs text-phosphor-400">
                  {item.linked_task_id}
                </span>
                <ExternalLink className="w-3 h-3 text-phosphor-500" />
              </div>
            </div>
          )}
        </div>

        {/* Resolution note */}
        {item.resolution_note && (
          <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
            <h3 className="text-xs font-medium text-emerald-400 mb-1">
              Resolution
            </h3>
            <p className="text-sm text-slate-300">{item.resolution_note}</p>
            {item.resolved_at && (
              <p className="text-2xs text-slate-500 mt-1">
                {new Date(item.resolved_at).toLocaleDateString()}
              </p>
            )}
          </div>
        )}

        {/* Votes */}
        <div>
          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-2">
            <ThumbsUp className="w-3 h-3" />
            Votes ({item.votes?.length ?? 0})
          </h3>
          {item.votes && item.votes.length > 0 ? (
            <div className="space-y-2">
              {item.votes.map((vote) => (
                <div
                  key={vote.id}
                  className="flex items-start gap-3 p-2.5 rounded-md bg-slate-800/40"
                >
                  <ThumbsUp className="w-3 h-3 text-slate-500 mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    {vote.comment && (
                      <p className="text-xs text-slate-300 mb-1">
                        {vote.comment}
                      </p>
                    )}
                    <div className="flex items-center gap-2 text-2xs text-slate-500">
                      {vote.agent_slug && <span>{vote.agent_slug}</span>}
                      <span>{new Date(vote.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-600">No votes yet</p>
          )}
        </div>
      </div>

      {/* Actions */}
      {item.status !== 'resolved' && item.status !== 'wont_fix' && (
        <div className="px-5 py-4 border-t border-slate-700/50 space-y-3">
          {showResolveInput ? (
            <div className="space-y-2">
              <input
                type="text"
                value={resolutionNote}
                onChange={(e) => setResolutionNote(e.target.value)}
                placeholder="Resolution note (optional)"
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg
                           text-sm text-slate-200 placeholder-slate-500
                           focus:outline-none focus:border-emerald-500/40"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={() =>
                    statusMutation.mutate({
                      status: 'resolved',
                      resolution_note: resolutionNote || undefined,
                    })
                  }
                  disabled={statusMutation.isPending}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 text-emerald-400
                             border border-emerald-500/30 rounded-md text-xs font-medium
                             hover:bg-emerald-500/30 transition-all disabled:opacity-50"
                >
                  {statusMutation.isPending ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Check className="w-3 h-3" />
                  )}
                  Confirm
                </button>
                <button
                  onClick={() => setShowResolveInput(false)}
                  className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {item.status === 'open' && (
                <button
                  onClick={() =>
                    statusMutation.mutate({ status: 'acknowledged' })
                  }
                  disabled={statusMutation.isPending}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500/10 text-amber-400
                             border border-amber-500/30 rounded-md text-xs font-medium
                             hover:bg-amber-500/20 transition-all disabled:opacity-50"
                >
                  <Clock className="w-3 h-3" />
                  Acknowledge
                </button>
              )}
              <button
                onClick={() => setShowResolveInput(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 text-emerald-400
                           border border-emerald-500/30 rounded-md text-xs font-medium
                           hover:bg-emerald-500/20 transition-all"
              >
                <Check className="w-3 h-3" />
                Resolve
              </button>
              <button
                onClick={() =>
                  statusMutation.mutate({ status: 'wont_fix' })
                }
                disabled={statusMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-500
                           hover:text-slate-400 transition-all disabled:opacity-50"
              >
                Won&apos;t Fix
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-2xs text-slate-500">{label}</span>
      <p className="text-xs text-slate-300 mt-0.5 capitalize">{value}</p>
    </div>
  )
}
