import { GitPullRequest, Loader2, X } from 'lucide-react'
import { useState } from 'react'
import type { WorktreeInfo } from '@/lib/api'

interface PRModalProps {
  worktree: WorktreeInfo
  onClose: () => void
  onConfirm: (title: string, body: string) => void
  isPending: boolean
}

export function PRModal({
  worktree,
  onClose,
  onConfirm,
  isPending,
}: PRModalProps) {
  const [title, setTitle] = useState(`feat: ${worktree.task_id}`)
  const [body, setBody] = useState(
    `## Summary\nImplemented ${worktree.task_id}\n\n## Changes\n- ${worktree.files_changed} files changed\n- +${worktree.additions} / -${worktree.deletions}`,
  )

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <h3 className="display text-lg font-semibold text-white">
            Create Pull Request
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
            <label className="block text-sm text-slate-400 mb-1.5">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-outrun-500"
            />
          </div>

          <div>
            <label className="block text-sm text-slate-400 mb-1.5">
              Description
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={6}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-outrun-500 resize-none"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={onClose}
              className="flex-1 btn-secondary"
              disabled={isPending}
            >
              Cancel
            </button>
            <button
              onClick={() => onConfirm(title, body)}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
              disabled={isPending || !title.trim()}
            >
              {isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <GitPullRequest className="w-4 h-4" />
              )}
              Create PR
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
