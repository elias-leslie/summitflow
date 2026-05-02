'use client'

import {
  AlertTriangle,
  ArrowLeft,
  FolderKanban,
  Home,
  RefreshCw,
  Search,
} from 'lucide-react'
import Link from 'next/link'

export function ProjectRouteErrorState({
  error,
  reset,
  scope,
}: {
  error: Error & { digest?: string }
  reset: () => void
  scope: 'project' | 'projects'
}) {
  const isProject = scope === 'project'

  return (
    <div className="flex items-center justify-center h-full min-h-[400px] p-6">
      <div className="card p-8 text-center max-w-md">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-rose-500/10 flex items-center justify-center">
          <AlertTriangle className="w-8 h-8 text-rose-500" />
        </div>
        <h2 className="display text-xl font-semibold text-slate-100 mb-2">
          {isProject ? 'Failed to load project' : 'Failed to load projects'}
        </h2>
        <p className="text-slate-400 mb-4">
          {isProject
            ? 'There was an error loading this project. The project may not exist or there was a connection issue.'
            : 'There was an error loading the projects section. Please try again.'}
        </p>
        {error.message && (
          <p className="text-xs text-slate-500 mono mb-2 px-3 py-2 bg-slate-800/50 rounded break-all">
            {error.message}
          </p>
        )}
        {error.digest && (
          <p className="text-xs text-slate-600 mono mb-4">
            Error ID: {error.digest}
          </p>
        )}
        <div className="flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={reset}
            className="btn-primary inline-flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>
          <Link
            href="/"
            className="btn-secondary inline-flex items-center gap-2"
          >
            {isProject ? (
              <ArrowLeft className="w-4 h-4" />
            ) : (
              <FolderKanban className="w-4 h-4" />
            )}
            {isProject ? 'Back to Dashboard' : 'Dashboard'}
          </Link>
        </div>
      </div>
    </div>
  )
}

export function ProjectNotFoundState() {
  return (
    <div className="flex items-center justify-center h-full min-h-[400px] p-6">
      <div className="card p-8 text-center max-w-md">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-amber-500/10 flex items-center justify-center">
          <Search className="w-8 h-8 text-amber-400" />
        </div>
        <h2 className="display text-xl font-semibold text-slate-100 mb-2">
          Project not found
        </h2>
        <p className="text-slate-400 mb-6">
          The project you are looking for does not exist or may have been
          deleted.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Link href="/" className="btn-primary inline-flex items-center gap-2">
            <Home className="w-4 h-4" />
            Dashboard
          </Link>
          <Link
            href="/projects/new"
            className="btn-secondary inline-flex items-center gap-2"
          >
            <FolderKanban className="w-4 h-4" />
            New Project
          </Link>
        </div>
      </div>
    </div>
  )
}
