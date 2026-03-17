'use client'

import clsx from 'clsx'
import {
  AlertTriangle,
  GitBranch,
  Layers,
  RefreshCw,
  Scissors,
  Unplug,
  XCircle,
} from 'lucide-react'
import { ConflictAlerts } from '@/components/git/ConflictAlerts'
import { ProjectRow } from '@/components/git/ProjectRow'
import { useGitStatus } from './useGitStatus'

function SummaryCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof GitBranch
  label: string
  value: number
  tone: string
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3">
      <div
        className={clsx(
          'mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.2em]',
          tone,
        )}
      >
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="text-2xl font-semibold text-white">{value}</div>
    </div>
  )
}

export function GitClient() {
  const { data: gitStatus, isLoading, isError, refetch } = useGitStatus()
  const repos = gitStatus?.repositories ?? []
  const configRepos = repos.filter((repo) => !repo.project_id)
  const needsAttention = (repo: (typeof repos)[number]) =>
    repo.state !== 'clean' ||
    (repo.workspace_summary?.dirty_worktrees ?? 0) > 0 ||
    (repo.workspace_summary?.orphan_branches ?? 0) > 0 ||
    (repo.workspace_summary?.prunable_branches ?? 0) > 0
  const reposNeedingCleanup = repos.filter((repo) =>
    needsAttention(repo),
  ).length
  const dirtyRepos = repos.filter(
    (repo) => repo.state === 'dirty' || repo.state === 'ahead',
  ).length
  const activeWorktrees = repos.reduce(
    (sum, repo) => sum + (repo.workspace_summary?.active_worktrees ?? 0),
    0,
  )
  const dirtyWorktrees = repos.reduce(
    (sum, repo) => sum + (repo.workspace_summary?.dirty_worktrees ?? 0),
    0,
  )
  const orphanBranches = repos.reduce(
    (sum, repo) => sum + (repo.workspace_summary?.orphan_branches ?? 0),
    0,
  )
  const prunableBranches = repos.reduce(
    (sum, repo) => sum + (repo.workspace_summary?.prunable_branches ?? 0),
    0,
  )

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header Section */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-4 animate-in fade-in slide-in-from-top-4 duration-500">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3 mb-2">
            <div className="p-2 rounded bg-outrun-500/10 border border-outrun-500/20">
              <GitBranch className="w-6 h-6 text-outrun-500" />
            </div>
            Git Operations
          </h1>
          <p className="text-slate-400 max-w-2xl">
            Command center for version control across all managed workspaces.
          </p>
          {configRepos.length > 0 && (
            <p className="mt-2 text-sm text-slate-500">
              Summary cards include managed config repos such as{' '}
              {configRepos.map((repo) => repo.name).join(', ')}.
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-md border border-slate-700 transition-all shadow-lg hover:shadow-phosphor-500/10 hover:border-phosphor-500/30"
        >
          <RefreshCw className={clsx('w-4 h-4', isLoading && 'animate-spin')} />
          <span>Refresh All</span>
        </button>
      </section>

      {/* Conflict Alerts — highest urgency, top of page */}
      <ConflictAlerts />

      {gitStatus && !isLoading && (
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <SummaryCard
            icon={GitBranch}
            label="Repos To Check"
            value={reposNeedingCleanup}
            tone="text-rose-300"
          />
          <SummaryCard
            icon={AlertTriangle}
            label="Dirty Repos"
            value={dirtyRepos}
            tone="text-orange-300"
          />
          <SummaryCard
            icon={Layers}
            label="Active Worktrees"
            value={activeWorktrees}
            tone="text-phosphor-300"
          />
          <SummaryCard
            icon={AlertTriangle}
            label="Dirty Worktrees"
            value={dirtyWorktrees}
            tone="text-orange-300"
          />
          <SummaryCard
            icon={Unplug}
            label="Orphan Branches"
            value={orphanBranches}
            tone="text-amber-300"
          />
          <SummaryCard
            icon={Scissors}
            label="Prunable Branches"
            value={prunableBranches}
            tone="text-outrun-300"
          />
        </section>
      )}

      {/* Project Rows */}
      {gitStatus && !isLoading && (
        <section className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
          {gitStatus.repositories.map((repo) => (
            <ProjectRow
              key={repo.path}
              repo={repo}
              isConfigRepo={!repo.project_id}
            />
          ))}
        </section>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="h-64 flex items-center justify-center border border-dashed border-slate-800 rounded-xl bg-slate-900/20">
          <div className="flex flex-col items-center gap-3 text-slate-500">
            <RefreshCw className="w-8 h-8 animate-spin text-phosphor-500" />
            <p>Scanning workspaces...</p>
          </div>
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="p-6 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-200 flex items-center gap-3">
          <XCircle className="w-6 h-6 text-rose-500" />
          <div>
            <h3 className="font-semibold text-white">Connection Failed</h3>
            <p className="text-sm opacity-80">
              Unable to reach the Git service. Please verify the backend is
              running.
            </p>
          </div>
        </div>
      )}

      {/* Empty State */}
      {gitStatus?.repositories.length === 0 && (
        <div className="text-center py-20">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-slate-800/50 mb-4">
            <GitBranch className="w-8 h-8 text-slate-600" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">
            No Repositories Found
          </h3>
          <p className="text-slate-400 max-w-sm mx-auto">
            Your workspace appears empty. Initialize a git repository to see it
            here.
          </p>
        </div>
      )}
    </div>
  )
}
