import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { getErrorMessage } from '@/lib/utils'

interface TaskQueryStateProps {
  children: ReactNode
  error: unknown
  isLoading: boolean
  loadingLabel: string
  onRetry: () => void
}

/** Keep task surfaces honest while their backing query is pending or failed. */
export function TaskQueryState({
  children,
  error,
  isLoading,
  loadingLabel,
  onRetry,
}: TaskQueryStateProps) {
  if (isLoading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-40 items-center justify-center rounded-lg border border-slate-700/80 bg-slate-900/50 px-6 py-12"
      >
        <div className="text-center text-slate-400">
          <Loader2 className="mx-auto h-6 w-6 animate-spin motion-reduce:animate-none" />
          <p className="mt-3 text-sm">{loadingLabel}</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        role="alert"
        className="flex min-h-40 items-center justify-center rounded-lg border border-rose-500/30 bg-rose-500/8 px-6 py-10"
      >
        <div className="max-w-md text-center">
          <AlertCircle className="mx-auto h-8 w-8 text-rose-400" />
          <p className="mt-3 text-sm font-medium text-slate-100">
            Failed to load tasks
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {getErrorMessage(error, 'Task data is temporarily unavailable')}
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:border-slate-600 hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Try again
          </button>
        </div>
      </div>
    )
  }

  return children
}
