'use client'

import type { UseMutationResult } from '@tanstack/react-query'
import { Check, Clock, Loader2, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { FeedbackStatus } from '@/lib/api/feedback'

type StatusMutationData = { status: FeedbackStatus; resolution_note?: string }

interface FeedbackDetailActionsProps {
  currentStatus: string
  statusMutation: UseMutationResult<unknown, Error, StatusMutationData>
  deleteMutation: UseMutationResult<unknown, Error, void>
  onDelete: () => void
}

export function FeedbackDetailActions({
  currentStatus,
  statusMutation,
  deleteMutation,
  onDelete,
}: FeedbackDetailActionsProps) {
  const [resolutionNote, setResolutionNote] = useState('')
  const [showResolveInput, setShowResolveInput] = useState(false)

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

  return (
    <>
      {/* Status actions */}
      {currentStatus !== 'archived' && (
        <div className="px-4 pt-3 pb-2 border-t border-slate-800/60 space-y-3">
          {showResolveInput ? (
            <div className="space-y-2">
              <input
                type="text"
                value={resolutionNote}
                onChange={(e) => setResolutionNote(e.target.value)}
                placeholder="Resolution note (optional)"
                className="w-full px-2.5 py-1.5 bg-slate-900/60 border border-slate-700/60 rounded
                           text-xs text-slate-200 placeholder-slate-500
                           focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
              />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleResolveConfirm}
                  disabled={statusMutation.isPending}
                  className="flex items-center gap-1.5 text-2xs px-2.5 py-1 rounded
                             bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20
                             disabled:opacity-40 transition-colors"
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
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {(currentStatus === 'open' ||
                currentStatus === 'acknowledged') && (
                <>
                  {currentStatus === 'open' && (
                    <button
                      type="button"
                      onClick={() =>
                        statusMutation.mutate({ status: 'acknowledged' })
                      }
                      disabled={statusMutation.isPending}
                      className="flex items-center gap-1.5 text-2xs px-2 py-1 rounded
                                 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20
                                 disabled:opacity-40 transition-colors"
                    >
                      <Clock className="w-3 h-3" />
                      Acknowledge
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowResolveInput(true)}
                    disabled={statusMutation.isPending}
                    className="flex items-center gap-1.5 text-2xs px-2 py-1 rounded
                               bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20
                               disabled:opacity-40 transition-colors"
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
                    className="text-2xs px-2 py-1 text-slate-500 hover:text-slate-400
                               disabled:opacity-40 transition-colors"
                  >
                    Won&apos;t Fix
                  </button>
                </>
              )}
              {(currentStatus === 'resolved' ||
                currentStatus === 'wont_fix') && (
                <button
                  type="button"
                  onClick={() => statusMutation.mutate({ status: 'archived' })}
                  disabled={statusMutation.isPending}
                  className="flex items-center gap-1.5 text-2xs px-2 py-1 rounded
                             bg-slate-700/40 text-slate-400 hover:bg-slate-700/60
                             disabled:opacity-40 transition-colors"
                >
                  Archive
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Delete */}
      <div className="px-4 py-2.5 border-t border-slate-800/60">
        <button
          type="button"
          onClick={onDelete}
          disabled={deleteMutation.isPending}
          className="flex items-center gap-1.5 text-2xs px-2 py-1 rounded
                     text-red-500/60 hover:text-red-400 hover:bg-red-500/10
                     disabled:opacity-40 transition-colors"
        >
          {deleteMutation.isPending ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Trash2 className="w-3 h-3" />
          )}
          Delete
        </button>
      </div>
    </>
  )
}
