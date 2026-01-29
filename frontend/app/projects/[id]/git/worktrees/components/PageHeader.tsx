import { ArrowLeft, Sparkles } from 'lucide-react'
import Link from 'next/link'

interface PageHeaderProps {
  projectId: string
  worktreeCount: number
  onCleanup: () => void
}

export function PageHeader({
  projectId,
  worktreeCount,
  onCleanup,
}: PageHeaderProps) {
  return (
    <header>
      <Link
        href={`/projects/${projectId}/git`}
        className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-phosphor-400 transition-colors mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Git Dashboard
      </Link>

      <div className="flex items-center gap-3 mb-2">
        <span className="mono text-xs text-outrun-500 uppercase tracking-widest">
          Git Control
        </span>
        <div className="h-px flex-1 bg-gradient-to-r from-outrun-500/50 via-slate-700 to-transparent" />
      </div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="display text-2xl font-bold text-white tracking-tight">
            Worktree Management
          </h1>
          <p className="text-slate-400 mt-1">
            {worktreeCount} active worktrees for isolated task execution
          </p>
        </div>
        {worktreeCount > 0 && (
          <button
            onClick={onCleanup}
            className="btn-secondary flex items-center gap-2"
          >
            <Sparkles className="w-4 h-4" />
            Cleanup Old
          </button>
        )}
      </div>
    </header>
  )
}
