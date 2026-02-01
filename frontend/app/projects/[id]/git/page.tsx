'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  FileEdit,
  GitBranch,
  Loader2,
  RefreshCw,
  Zap,
} from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import {
  fetchProjectGitStatus,
  type RepoStatus,
  type SyncResult,
  syncRepositories,
} from '@/lib/api'

export default function GitDashboardPage() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()
  const [syncResults, setSyncResults] = useState<SyncResult[] | null>(null)

  const {
    data: gitStatus,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['git-status', projectId],
    queryFn: () => fetchProjectGitStatus(projectId),
    refetchInterval: 30000,
  })

  const syncMutation = useMutation({
    mutationFn: syncRepositories,
    onSuccess: (data) => {
      setSyncResults(data.results)
      queryClient.invalidateQueries({ queryKey: ['git-status', projectId] })
      setTimeout(() => setSyncResults(null), 5000)
    },
  })

  const handleSync = () => {
    setSyncResults(null)
    syncMutation.mutate()
  }

  const getStateColor = (state: RepoStatus['state']) => {
    switch (state) {
      case 'clean':
        return 'phosphor'
      case 'dirty':
        return 'outrun'
      case 'behind':
        return 'amber'
      case 'ahead':
        return 'sunset'
      default:
        return 'slate'
    }
  }

  const getStateIcon = (state: RepoStatus['state']) => {
    switch (state) {
      case 'clean':
        return <CheckCircle2 className="w-4 h-4" />
      case 'dirty':
        return <FileEdit className="w-4 h-4" />
      case 'behind':
        return <ArrowDown className="w-4 h-4" />
      case 'ahead':
        return <ArrowUp className="w-4 h-4" />
      default:
        return null
    }
  }

  const getStateLabel = (state: RepoStatus['state']) => {
    switch (state) {
      case 'clean':
        return 'Synced'
      case 'dirty':
        return 'Modified'
      case 'behind':
        return 'Behind'
      case 'ahead':
        return 'Ahead'
      default:
        return state
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="card p-8 text-center max-w-md">
          <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-4" />
          <h2 className="display text-lg font-semibold text-white mb-2">
            Failed to Load
          </h2>
          <p className="text-slate-400 mb-6">
            Could not connect to git status service.
          </p>
          <button onClick={() => refetch()} className="btn-primary">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const repos = gitStatus?.repositories ?? []
  const cleanCount = repos.filter((r) => r.state === 'clean').length
  const dirtyCount = repos.filter((r) => r.state === 'dirty').length

  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <header className="relative">
        <div className="flex items-center gap-3 mb-2">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">
            Git Control
          </span>
          <div className="h-px flex-1 bg-gradient-to-r from-phosphor-500/50 via-outrun-500/30 to-transparent" />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="display text-3xl font-bold text-white tracking-tight">
              Repository Status
            </h1>
            <p className="text-slate-400 mt-1">
              Monitor and sync managed repositories
            </p>
          </div>

          {/* Sync All Button */}
          <button
            onClick={handleSync}
            disabled={syncMutation.isPending}
            className="relative group flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-phosphor-600 to-phosphor-500 text-slate-900 font-semibold rounded-lg transition-all hover:shadow-[0_0_30px_rgba(0,245,255,0.4)] disabled:opacity-50 disabled:cursor-not-allowed overflow-hidden"
          >
            {/* Shimmer effect */}
            <div className="absolute inset-0 -translate-x-full group-hover:translate-x-full transition-transform duration-700 bg-gradient-to-r from-transparent via-white/20 to-transparent" />

            {syncMutation.isPending ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <RefreshCw className="w-5 h-5" />
            )}
            <span>{syncMutation.isPending ? 'Syncing...' : 'Sync All'}</span>

            {/* Glow ring when syncing */}
            {syncMutation.isPending && (
              <span className="absolute inset-0 rounded-lg animate-pulse ring-2 ring-phosphor-400/50" />
            )}
          </button>
        </div>

        {/* Quick Stats Bar */}
        <div className="mt-6 flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.6)]" />
            <span className="text-sm text-slate-300">{cleanCount} Clean</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-outrun-500 shadow-[0_0_8px_rgba(255,0,102,0.6)]" />
            <span className="text-sm text-slate-300">
              {dirtyCount} Modified
            </span>
          </div>
        </div>
      </header>

      {/* Sync Results Toast */}
      {syncResults && (
        <div className="fixed top-20 right-6 z-50 animate-slide-up">
          <div className="card p-4 border border-phosphor-500/30 shadow-[0_0_20px_rgba(0,245,255,0.2)]">
            <div className="flex items-center gap-3 mb-2">
              <Zap className="w-5 h-5 text-phosphor-500" />
              <span className="font-semibold text-white">Sync Complete</span>
            </div>
            <div className="space-y-1 text-sm">
              {syncResults.map((result) => (
                <div
                  key={result.path}
                  className="flex items-center gap-2 text-slate-300"
                >
                  <span className="mono text-xs text-slate-500">
                    {result.name}
                  </span>
                  <span
                    className={
                      result.status === 'updated'
                        ? 'text-phosphor-500'
                        : result.status === 'skipped'
                          ? 'text-amber-400'
                          : result.status === 'failed'
                            ? 'text-rose-400'
                            : 'text-slate-400'
                    }
                  >
                    {result.status === 'up_to_date'
                      ? 'Up to date'
                      : result.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Repository Cards Grid */}
      <section>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {repos.map((repo) => {
            const stateColor = getStateColor(repo.state)

            return (
              <div
                key={repo.path}
                className={`
                  relative group card p-5 transition-all duration-300
                  hover:shadow-${stateColor === 'phosphor' ? '[0_0_25px_rgba(0,245,255,0.15)]' : stateColor === 'outrun' ? '[0_0_25px_rgba(255,0,102,0.15)]' : '[0_0_25px_rgba(255,102,0,0.15)]'}
                  border-l-2 border-l-${stateColor}-500
                `}
                style={{
                  borderLeftColor:
                    stateColor === 'phosphor'
                      ? '#00f5ff'
                      : stateColor === 'outrun'
                        ? '#ff0066'
                        : stateColor === 'amber'
                          ? '#fbbf24'
                          : '#ff6600',
                }}
              >
                {/* Glow orb */}
                <div
                  className="absolute top-4 right-4 w-8 h-8 rounded-full opacity-20 blur-lg transition-opacity group-hover:opacity-40"
                  style={{
                    backgroundColor:
                      stateColor === 'phosphor'
                        ? '#00f5ff'
                        : stateColor === 'outrun'
                          ? '#ff0066'
                          : stateColor === 'amber'
                            ? '#fbbf24'
                            : '#ff6600',
                  }}
                />

                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="display font-semibold text-lg text-white">
                      {repo.name}
                    </h3>
                    <p className="mono text-xs text-slate-500 truncate max-w-[200px]">
                      {repo.path}
                    </p>
                  </div>
                  <div
                    className={`
                      flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
                      ${
                        stateColor === 'phosphor'
                          ? 'bg-phosphor-500/10 text-phosphor-400'
                          : stateColor === 'outrun'
                            ? 'bg-outrun-500/10 text-outrun-400'
                            : stateColor === 'amber'
                              ? 'bg-amber-500/10 text-amber-400'
                              : 'bg-sunset-orange/10 text-sunset-orange'
                      }
                    `}
                  >
                    {getStateIcon(repo.state)}
                    {getStateLabel(repo.state)}
                  </div>
                </div>

                {/* Branch */}
                <div className="flex items-center gap-2 mb-4">
                  <GitBranch className="w-4 h-4 text-slate-500" />
                  <span className="mono text-sm text-slate-300">
                    {repo.branch}
                  </span>
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="text-center p-2 rounded bg-slate-800/50">
                    <div
                      className={`text-lg font-bold ${repo.uncommitted > 0 ? 'text-outrun-400' : 'text-slate-500'}`}
                    >
                      {repo.uncommitted}
                    </div>
                    <div className="text-2xs text-slate-500 uppercase tracking-wide">
                      Modified
                    </div>
                  </div>
                  <div className="text-center p-2 rounded bg-slate-800/50">
                    <div
                      className={`text-lg font-bold ${repo.ahead > 0 ? 'text-sunset-orange' : 'text-slate-500'}`}
                    >
                      {repo.ahead}
                    </div>
                    <div className="text-2xs text-slate-500 uppercase tracking-wide">
                      Ahead
                    </div>
                  </div>
                  <div className="text-center p-2 rounded bg-slate-800/50">
                    <div
                      className={`text-lg font-bold ${repo.behind > 0 ? 'text-amber-400' : 'text-slate-500'}`}
                    >
                      {repo.behind}
                    </div>
                    <div className="text-2xs text-slate-500 uppercase tracking-wide">
                      Behind
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}
