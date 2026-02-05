'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CheckCircle,
  GitBranch,
  RefreshCw,
} from 'lucide-react'
import { WorktreeList } from '@/components/git/WorktreeList'
import { fetchGitStatus, type RepoStatus } from '@/lib/api'

function getStateInfo(state: RepoStatus['state']) {
  switch (state) {
    case 'clean':
      return {
        label: 'Clean',
        icon: CheckCircle,
        color: 'text-emerald-400',
        bg: 'bg-emerald-500/10',
        border: 'border-emerald-500/30',
      }
    case 'dirty':
      return {
        label: 'Dirty',
        icon: AlertCircle,
        color: 'text-amber-400',
        bg: 'bg-amber-500/10',
        border: 'border-amber-500/30',
      }
    case 'behind':
      return {
        label: 'Behind',
        icon: ArrowDown,
        color: 'text-rose-400',
        bg: 'bg-rose-500/10',
        border: 'border-rose-500/30',
      }
    case 'ahead':
      return {
        label: 'Ahead',
        icon: ArrowUp,
        color: 'text-violet-400',
        bg: 'bg-violet-500/10',
        border: 'border-violet-500/30',
      }
    default:
      return {
        label: state,
        icon: GitBranch,
        color: 'text-slate-400',
        bg: 'bg-slate-500/10',
        border: 'border-slate-500/30',
      }
  }
}

function GitProjectCard({ repo }: { repo: RepoStatus }) {
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon

  return (
    <div
      data-testid="git-project-card"
      className={clsx(
        'card-elevated p-5 rounded-lg transition-all duration-200',
        'hover:border-violet-500/50 hover:shadow-[0_0_20px_rgba(139,92,246,0.15)]',
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-violet-500/15 flex items-center justify-center">
            <GitBranch className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">{repo.name}</h3>
            <p className="text-xs text-slate-500 mono truncate max-w-[200px]">
              {repo.path}
            </p>
          </div>
        </div>

        {/* Status Badge */}
        <div
          className={clsx(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
            stateInfo.bg,
            stateInfo.color,
            stateInfo.border,
          )}
        >
          <StateIcon className="w-3.5 h-3.5" />
          {stateInfo.label}
        </div>
      </div>

      {/* Branch */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-slate-500 uppercase tracking-wider">
          Branch:
        </span>
        <span className="text-sm text-slate-300 mono">{repo.branch}</span>
      </div>

      {/* Stats Row */}
      <div className="flex items-center gap-4 text-sm">
        {repo.uncommitted > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-amber-400 font-medium">
              {repo.uncommitted}
            </span>
            <span className="text-slate-500">uncommitted</span>
          </div>
        )}
        {repo.ahead > 0 && (
          <div className="flex items-center gap-1.5">
            <ArrowUp className="w-3.5 h-3.5 text-violet-400" />
            <span className="text-violet-400 font-medium">{repo.ahead}</span>
            <span className="text-slate-500">ahead</span>
          </div>
        )}
        {repo.behind > 0 && (
          <div className="flex items-center gap-1.5">
            <ArrowDown className="w-3.5 h-3.5 text-rose-400" />
            <span className="text-rose-400 font-medium">{repo.behind}</span>
            <span className="text-slate-500">behind</span>
          </div>
        )}
        {repo.uncommitted === 0 && repo.ahead === 0 && repo.behind === 0 && (
          <span className="text-slate-500 text-xs">Up to date</span>
        )}
      </div>

      {/* Action buttons placeholder for future CRUD */}
      <div className="mt-4 pt-4 border-t border-slate-700/50 flex items-center gap-2">
        <span className="text-xs text-slate-600 italic">
          Actions coming soon...
        </span>
      </div>
    </div>
  )
}

export function GitClient() {
  const {
    data: gitStatus,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['git-status'],
    queryFn: fetchGitStatus,
    staleTime: 30000,
    refetchInterval: 60000,
  })

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <section className="animate-in">
        <div className="flex items-center justify-between mb-4">
          <h1 className="display font-semibold text-2xl text-white flex items-center gap-3">
            <GitBranch className="w-7 h-7 text-violet-400" />
            Git Repositories
          </h1>
          <button
            onClick={() => refetch()}
            className="btn-secondary flex items-center gap-2 text-sm"
          >
            <RefreshCw
              className={clsx('w-4 h-4', isLoading && 'animate-spin')}
            />
            Refresh
          </button>
        </div>
        <p className="text-slate-400">
          View and manage git status across all managed repositories.
        </p>
      </section>

      {/* Active Worktrees Section */}
      <WorktreeList />

      {/* Summary */}
      {gitStatus && (
        <section className="animate-in stagger-1">
          <div className="flex items-center gap-6 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-slate-500">Total:</span>
              <span className="text-white font-semibold">
                {gitStatus.total} repos
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-emerald-400 font-semibold">
                {
                  gitStatus.repositories.filter((r) => r.state === 'clean')
                    .length
                }
              </span>
              <span className="text-slate-500">clean</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-amber-400 font-semibold">
                {
                  gitStatus.repositories.filter((r) => r.state === 'dirty')
                    .length
                }
              </span>
              <span className="text-slate-500">dirty</span>
            </div>
            {gitStatus.repositories.filter((r) => r.behind > 0).length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-rose-400 font-semibold">
                  {gitStatus.repositories.filter((r) => r.behind > 0).length}
                </span>
                <span className="text-slate-500">behind remote</span>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="card p-8 text-center">
          <div className="inline-flex items-center gap-2 text-slate-400">
            <div className="w-4 h-4 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
            Loading repositories...
          </div>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="card p-6 border-rose-500/30">
          <div className="flex items-center gap-3 text-rose-400">
            <AlertCircle className="w-5 h-5" />
            <span>Failed to load git status. Please try again.</span>
          </div>
        </div>
      )}

      {/* Repository Grid */}
      {gitStatus && !isLoading && (
        <section className="animate-in stagger-2">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {gitStatus.repositories.map((repo) => (
              <GitProjectCard key={repo.path} repo={repo} />
            ))}
          </div>
        </section>
      )}

      {/* Empty State */}
      {gitStatus?.repositories.length === 0 && (
        <div className="card p-8 text-center">
          <GitBranch className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400">No repositories configured.</p>
        </div>
      )}
    </div>
  )
}
