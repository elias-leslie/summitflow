'use client'

import clsx from 'clsx'
import { GitBranch, RefreshCw, XCircle } from 'lucide-react'
import { ConflictAlerts } from '@/components/git/ConflictAlerts'
import { ProjectRow } from '@/components/git/ProjectRow'
import { useGitStatus } from './useGitStatus'

export function GitClient() {
  const { data: gitStatus, isLoading, isError, refetch } = useGitStatus()

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header Section */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-4 animate-in fade-in slide-in-from-top-4 duration-500">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3 mb-2">
            <div className="p-2 rounded bg-pink-500/10 border border-pink-500/20">
              <GitBranch className="w-6 h-6 text-pink-500" />
            </div>
            Git Operations
          </h1>
          <p className="text-slate-400 max-w-2xl">
            Command center for version control across all managed workspaces.
          </p>
        </div>

        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-md border border-slate-700 transition-all shadow-lg hover:shadow-cyan-500/10 hover:border-cyan-500/30"
        >
          <RefreshCw className={clsx('w-4 h-4', isLoading && 'animate-spin')} />
          <span>Refresh All</span>
        </button>
      </section>

      {/* Conflict Alerts — highest urgency, top of page */}
      <ConflictAlerts />

      {/* Project Rows */}
      {gitStatus && !isLoading && (
        <section className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
          {gitStatus.repositories.map((repo) => (
            <ProjectRow
              key={repo.path}
              repo={repo}
              isConfigRepo={repo.name === '.claude'}
            />
          ))}
        </section>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="h-64 flex items-center justify-center border border-dashed border-slate-800 rounded-xl bg-slate-900/20">
          <div className="flex flex-col items-center gap-3 text-slate-500">
            <RefreshCw className="w-8 h-8 animate-spin text-cyan-500" />
            <p>Scanning workspaces...</p>
          </div>
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-red-200 flex items-center gap-3">
          <XCircle className="w-6 h-6 text-red-500" />
          <div>
            <h3 className="font-semibold text-white">Connection Failed</h3>
            <p className="text-sm opacity-80">Unable to reach the Git service. Please verify the backend is running.</p>
          </div>
        </div>
      )}

      {/* Empty State */}
      {gitStatus?.repositories.length === 0 && (
        <div className="text-center py-20">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-slate-800/50 mb-4">
            <GitBranch className="w-8 h-8 text-slate-600" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No Repositories Found</h3>
          <p className="text-slate-400 max-w-sm mx-auto">
            Your workspace appears empty. Initialize a git repository to see it here.
          </p>
        </div>
      )}
    </div>
  )
}
