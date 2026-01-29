import { useMutation } from '@tanstack/react-query'
import { Clock, Loader2, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { type CleanupResponse, cleanupWorktrees } from '@/lib/api'

interface CleanupModalProps {
  projectId: string
  onClose: () => void
  onSuccess: () => void
}

export function CleanupModal({
  projectId,
  onClose,
  onSuccess,
}: CleanupModalProps) {
  const [maxAgeDays, setMaxAgeDays] = useState(30)
  const [previewData, setPreviewData] = useState<CleanupResponse | null>(null)

  const previewMutation = useMutation({
    mutationFn: () => cleanupWorktrees(projectId, maxAgeDays, true),
    onSuccess: setPreviewData,
  })

  const cleanupMutation = useMutation({
    mutationFn: () => cleanupWorktrees(projectId, maxAgeDays, false),
    onSuccess: () => {
      onSuccess()
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <h3 className="display text-lg font-semibold text-white">
            Cleanup Old Worktrees
          </h3>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1.5">
              Remove worktrees older than
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={maxAgeDays}
                onChange={(e) =>
                  setMaxAgeDays(parseInt(e.target.value, 10) || 30)
                }
                min={1}
                max={365}
                className="w-24 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-outrun-500"
              />
              <span className="text-slate-400">days</span>
              <button
                onClick={() => previewMutation.mutate()}
                className="ml-auto btn-secondary text-sm"
                disabled={previewMutation.isPending}
              >
                {previewMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  'Preview'
                )}
              </button>
            </div>
          </div>

          {previewData && (
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 uppercase mb-2">
                Would Remove
              </div>
              {previewData.would_remove.length > 0 ? (
                <div className="space-y-1 max-h-40 overflow-auto">
                  {previewData.would_remove.map((item, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="mono text-slate-300">
                        {item.task_id}
                      </span>
                      <span className="text-slate-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {item.age_days} days old
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-400 text-sm">
                  No worktrees older than {maxAgeDays} days
                </p>
              )}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button onClick={onClose} className="flex-1 btn-secondary">
              Cancel
            </button>
            <button
              onClick={() => cleanupMutation.mutate()}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
              disabled={
                cleanupMutation.isPending ||
                !previewData ||
                previewData.would_remove.length === 0
              }
            >
              {cleanupMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              Cleanup
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
