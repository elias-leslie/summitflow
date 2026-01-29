import {
  ExternalLink,
  Eye,
  FileCode2,
  GitBranch,
  GitMerge,
  GitPullRequest,
  Loader2,
  Minus,
  Plus,
  Trash2,
  Upload,
} from 'lucide-react'
import Link from 'next/link'
import type { WorktreeInfo } from '@/lib/api'

interface WorktreeCardProps {
  worktree: WorktreeInfo
  projectId: string
  deleteTarget: string | null
  onDelete: (taskId: string) => void
  isDeleting: boolean
  onViewDiff: () => void
  onMerge: () => void
  onPush: () => void
  onCreatePR: () => void
  isPushing: boolean
}

export function WorktreeCard({
  worktree,
  projectId,
  deleteTarget,
  onDelete,
  isDeleting,
  onViewDiff,
  onMerge,
  onPush,
  onCreatePR,
  isPushing,
}: WorktreeCardProps) {
  const isConfirming = deleteTarget === worktree.task_id

  return (
    <div className="card p-5 group hover:border-outrun-500/30 transition-colors">
      <div className="flex items-start justify-between gap-4">
        {/* Left: Task and Branch Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <Link
              href={`/projects/${projectId}?tab=kanban&task=${worktree.task_id}`}
              className="mono font-medium text-white hover:text-outrun-400 transition-colors"
            >
              {worktree.task_id}
            </Link>
            <ExternalLink className="w-3 h-3 text-slate-500" />
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-400">
            <GitBranch className="w-4 h-4 text-slate-500" />
            <span className="mono truncate">{worktree.branch}</span>
          </div>

          <div className="mono text-xs text-slate-500 truncate mt-1">
            {worktree.path}
          </div>
        </div>

        {/* Middle: Stats */}
        <div className="flex items-center gap-6">
          <div className="text-center">
            <div className="flex items-center gap-1 text-slate-300">
              <FileCode2 className="w-4 h-4 text-slate-500" />
              <span className="font-medium">{worktree.commit_count}</span>
            </div>
            <div className="text-2xs text-slate-500 uppercase mt-0.5">
              Commits
            </div>
          </div>

          <div className="text-center">
            <div className="font-medium text-slate-300">
              {worktree.files_changed}
            </div>
            <div className="text-2xs text-slate-500 uppercase mt-0.5">
              Files
            </div>
          </div>

          <div className="text-center">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-0.5 text-emerald-400">
                <Plus className="w-3 h-3" />
                {worktree.additions}
              </span>
              <span className="flex items-center gap-0.5 text-rose-400">
                <Minus className="w-3 h-3" />
                {worktree.deletions}
              </span>
            </div>
            <div className="text-2xs text-slate-500 uppercase mt-0.5">
              Changes
            </div>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-1">
          <button
            onClick={onViewDiff}
            className="p-2 rounded text-slate-500 hover:text-phosphor-400 hover:bg-slate-800 transition-all"
            title="View diff"
          >
            <Eye className="w-4 h-4" />
          </button>

          <button
            onClick={onMerge}
            className="p-2 rounded text-slate-500 hover:text-emerald-400 hover:bg-slate-800 transition-all"
            title="Merge to main"
          >
            <GitMerge className="w-4 h-4" />
          </button>

          <button
            onClick={onPush}
            disabled={isPushing}
            className="p-2 rounded text-slate-500 hover:text-sky-400 hover:bg-slate-800 transition-all disabled:opacity-50"
            title="Push to origin"
          >
            {isPushing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Upload className="w-4 h-4" />
            )}
          </button>

          <button
            onClick={onCreatePR}
            className="p-2 rounded text-slate-500 hover:text-violet-400 hover:bg-slate-800 transition-all"
            title="Create pull request"
          >
            <GitPullRequest className="w-4 h-4" />
          </button>

          <div className="w-px h-6 bg-slate-700 mx-1" />

          <button
            onClick={() => onDelete(worktree.task_id)}
            disabled={isDeleting}
            className={`
              p-2 rounded transition-all
              ${
                isConfirming
                  ? 'bg-rose-500/20 text-rose-400 ring-1 ring-rose-500/50'
                  : 'text-slate-500 hover:text-rose-400 hover:bg-slate-800'
              }
              disabled:opacity-50
            `}
            title={isConfirming ? 'Click again to confirm' : 'Delete worktree'}
          >
            {isDeleting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Confirmation Message */}
      {isConfirming && (
        <div className="mt-3 pt-3 border-t border-slate-800 text-sm text-rose-400">
          Click delete again to confirm. This will remove the worktree and its
          branch.
        </div>
      )}
    </div>
  )
}
