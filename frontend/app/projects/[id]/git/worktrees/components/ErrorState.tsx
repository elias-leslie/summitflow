import { AlertTriangle } from 'lucide-react'

interface ErrorStateProps {
  onRetry: () => void
}

export function ErrorState({ onRetry }: ErrorStateProps) {
  return (
    <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
      <div className="card p-8 text-center max-w-md">
        <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-4" />
        <h2 className="display text-lg font-semibold text-white mb-2">
          Failed to Load
        </h2>
        <p className="text-slate-400 mb-6">
          Could not fetch worktree information.
        </p>
        <button onClick={onRetry} className="btn-primary">
          Retry
        </button>
      </div>
    </div>
  )
}
