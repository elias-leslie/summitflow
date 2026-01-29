import { GitMerge, Loader2 } from 'lucide-react'
import type { WorktreeInfo } from '@/lib/api'

interface MergeModalProps {
  worktree: WorktreeInfo
  onClose: () => void
  onConfirm: () => void
  isPending: boolean
}

export function MergeModal({
  worktree,
  onClose,
  onConfirm,
  isPending,
}: MergeModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md">
        <div className="p-6">
          <div className="w-12 h-12 rounded-full bg-emerald-500/20 flex items-center justify-center mx-auto mb-4">
            <GitMerge className="w-6 h-6 text-emerald-400" />
          </div>
          <h3 className="display text-lg font-semibold text-white text-center mb-2">
            Merge to Main?
          </h3>
          <p className="text-slate-400 text-center text-sm mb-6">
            This will merge{' '}
            <span className="mono text-phosphor-400">{worktree.branch}</span>{' '}
            into main and delete the worktree.
          </p>

          <div className="bg-slate-800/50 rounded-lg p-3 mb-6">
            <div className="text-xs text-slate-500 uppercase mb-1">Changes</div>
            <div className="flex items-center gap-4 text-sm">
              <span className="text-slate-300">
                {worktree.commit_count} commits
              </span>
              <span className="text-emerald-400">+{worktree.additions}</span>
              <span className="text-rose-400">-{worktree.deletions}</span>
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 btn-secondary"
              disabled={isPending}
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
              disabled={isPending}
            >
              {isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <GitMerge className="w-4 h-4" />
              )}
              Merge
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
