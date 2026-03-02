'use client'

import { Check, Clock, Loader2, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { UseMutationResult } from '@tanstack/react-query'

// ============================================================================
// Types
// ============================================================================

type StatusMutationData = { status: string; resolution_note?: string }

interface FeedbackDetailActionsProps {
  currentStatus: string
  statusMutation: UseMutationResult<unknown, Error, StatusMutationData>
  deleteMutation: UseMutationResult<unknown, Error, void>
}

// ============================================================================
// Component
// ============================================================================

export function FeedbackDetailActions({
  currentStatus,
  statusMutation,
  deleteMutation,
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

  const handleDelete = () => {
    if (window.confirm('Delete this feedback item? This cannot be undone.')) {
      deleteMutation.mutate()
    }
  }

  return (
    <>
      {/* Status actions — hidden once resolved or won't fix */}
      {currentStatus !== 'resolved' && currentStatus !== 'wont_fix' && (
        <div className="px-5 pt-4 pb-2 border-t border-slate-700/50 space-y-3">
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
                  onClick={handleResolveConfirm}
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
              {currentStatus === 'open' && (
                <button
                  onClick={() => statusMutation.mutate({ status: 'acknowledged' })}
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
                disabled={statusMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 text-emerald-400
                           border border-emerald-500/30 rounded-md text-xs font-medium
                           hover:bg-emerald-500/20 transition-all disabled:opacity-50"
              >
                <Check className="w-3 h-3" />
                Resolve
              </button>
              <button
                onClick={() => statusMutation.mutate({ status: 'wont_fix' })}
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

      {/* Delete — always available */}
      <div className="px-5 py-3 border-t border-slate-700/50">
        <button
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-rose-500/60
                     hover:text-rose-400 hover:bg-rose-500/10 rounded-md
                     transition-all disabled:opacity-50"
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
