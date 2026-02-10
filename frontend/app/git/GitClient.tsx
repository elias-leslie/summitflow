'use client'

import clsx from 'clsx'
import { AlertCircle, GitBranch, RefreshCw, GitPullRequest, Clock, XCircle } from 'lucide-react'
import { WorktreeList } from '@/components/git/WorktreeList'
import { StatsWidget } from './StatsWidget'
import { GitProjectCard } from './GitProjectCard'
import { useGitStatus } from './useGitStatus'

export function GitClient() {
  const { data: gitStatus, isLoading, isError, refetch } = useGitStatus()

  // Derived Stats
  const totalRepos = gitStatus?.total ?? 0
  const dirtyCount = gitStatus?.repositories.filter(r => r.state === 'dirty').length ?? 0
  const syncCount = gitStatus?.repositories.filter(r => r.behind > 0 || r.ahead > 0).length ?? 0

  return (
    <div className="p-6 space-y-8 max-w-7xl mx-auto">
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

      <WorktreeList />

      {/* Stats Dashboard */}
      {gitStatus && (
        <section className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-in fade-in slide-in-from-top-8 delay-100 duration-500">
          <StatsWidget
            label="Total Repositories"
            value={totalRepos}
            icon={GitPullRequest}
            color="text-white"
          />
          <StatsWidget
            label="Changes Pending"
            value={dirtyCount}
            icon={AlertCircle}
            color={dirtyCount > 0 ? "text-pink-500" : "text-slate-500"}
          />
          <StatsWidget
            label="Sync Required"
            value={syncCount}
            icon={Clock}
            color={syncCount > 0 ? "text-cyan-400" : "text-emerald-500"}
          />
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

      {/* Main Grid */}
      {gitStatus && !isLoading && (
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-in fade-in slide-in-from-bottom-8 delay-200 duration-500">
          {gitStatus.repositories.map((repo) => (
            <GitProjectCard key={repo.path} repo={repo} />
          ))}
        </section>
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
