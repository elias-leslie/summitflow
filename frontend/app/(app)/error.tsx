'use client'

import { AlertTriangle, RefreshCw } from 'lucide-react'
import { useEffect } from 'react'

interface ErrorProps {
  error: Error & { digest?: string }
  reset: () => void
}

export default function Error({ error, reset }: ErrorProps) {
  useEffect(() => {
    // Log the error to an error reporting service
    console.error('Application error:', error)
  }, [error])

  return (
    <div className="flex items-center justify-center h-full min-h-[400px] p-6">
      <div className="card-elevated p-10 text-center max-w-md relative overflow-hidden">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-32 bg-rose-500/8 rounded-full blur-3xl pointer-events-none" />
        <div className="relative">
          <div className="w-18 h-18 mx-auto mb-5 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center animate-in stagger-1">
            <AlertTriangle className="w-9 h-9 text-rose-400" />
          </div>
          <h2 className="display text-2xl font-bold text-slate-100 mb-2 tracking-tight animate-in stagger-2">
            Something went wrong
          </h2>
          <p className="text-sm text-slate-400 mb-6 leading-relaxed animate-in stagger-3">
            An unexpected error occurred. Please try again or contact support if
            the problem persists.
          </p>
          {error.message && (
            <p className="text-xs text-slate-500 mono mb-3 px-3 py-2.5 bg-slate-950/60 border border-slate-800/70 rounded-lg break-all animate-in stagger-3">
              {error.message}
            </p>
          )}
          {error.digest && (
            <p className="text-xs text-slate-600 mono mb-6">
              Error ID: {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={reset}
            className="btn-primary inline-flex items-center gap-2 animate-in stagger-4"
          >
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>
        </div>
      </div>
    </div>
  )
}
