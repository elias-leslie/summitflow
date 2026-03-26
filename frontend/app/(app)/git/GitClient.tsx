'use client'

import clsx from 'clsx'
import {
  AlertTriangle,
  GitBranch,
  Layers,
  RefreshCw,
  Scissors,
  XCircle,
} from 'lucide-react'
import { motion } from 'motion/react'
import { ConflictAlerts } from '@/components/git/ConflictAlerts'
import { ProjectRow } from '@/components/git/ProjectRow'
import { useGitCleanupStatus, useGitStatus } from './useGitStatus'

const fadeUp = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
}

function StatPill({
  icon: Icon,
  value,
  label,
  tone,
}: {
  icon: typeof GitBranch
  value: number
  label: string
  tone: string
}) {
  if (value === 0) return null
  return (
    <div
      className={clsx(
        'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono tabular-nums',
        tone,
      )}
    >
      <Icon className="w-3 h-3" />
      <span className="font-semibold">{value}</span>
      <span className="opacity-60 hidden sm:inline">{label}</span>
    </div>
  )
}

export function GitClient() {
  const { data: gitStatus, isLoading, isError } = useGitStatus()
  const { data: cleanupStatus } = useGitCleanupStatus()
  const repos = gitStatus?.repositories ?? []
  const cleanupSummary = cleanupStatus?.payload.summary

  const dirtyRepos = repos.filter(
    (r) => r.state === 'dirty' || r.state === 'ahead',
  ).length
  const activeWorktreesFallback = repos.reduce(
    (s, r) => s + (r.workspace_summary?.active_worktrees ?? 0),
    0,
  )
  const dirtyWorktreesFallback = repos.reduce(
    (s, r) => s + (r.workspace_summary?.dirty_worktrees ?? 0),
    0,
  )
  const orphanBranches = repos.reduce(
    (s, r) => s + (r.workspace_summary?.orphan_branches ?? 0),
    0,
  )
  const prunableBranches = repos.reduce(
    (s, r) => s + (r.workspace_summary?.prunable_branches ?? 0),
    0,
  )
  const worktreeCount = cleanupSummary?.active_worktrees ?? activeWorktreesFallback
  const dirtyCount = cleanupSummary?.dirty_worktrees ?? dirtyWorktreesFallback
  const cleanupCount =
    cleanupSummary?.repos_needing_cleanup ?? orphanBranches + prunableBranches
  const hasSignals = dirtyCount + worktreeCount + cleanupCount + dirtyRepos > 0

  return (
    <div className="mx-auto max-w-[1400px] space-y-3 px-4 py-3 md:px-5 lg:px-6">
      <motion.section
        {...fadeUp}
        transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="space-y-3"
      >
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <GitBranch className="h-5 w-5 text-outrun-400" />
            <div>
              <h1 className="display text-xl font-semibold tracking-tight text-slate-50">
                Git Control Surface
              </h1>
              <p className="text-sm text-slate-400">
                Repo hygiene, worktrees, and branch cleanup
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {gitStatus && !isLoading && hasSignals ? (
              <>
                <StatPill
                  icon={AlertTriangle}
                  value={dirtyCount}
                  label="dirty"
                  tone="bg-pink-500/8 text-pink-300 border-pink-500/20"
                />
                <StatPill
                  icon={Layers}
                  value={worktreeCount}
                  label="worktrees"
                  tone="bg-phosphor-500/8 text-phosphor-300 border-phosphor-500/20"
                />
                <StatPill
                  icon={Scissors}
                  value={cleanupCount}
                  label="cleanup"
                  tone="bg-amber-500/8 text-amber-300 border-amber-500/20"
                />
              </>
            ) : (
              <span className="rounded-full border border-emerald-500/18 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200">
                All repos clean
              </span>
            )}
          </div>
        </div>

      </motion.section>

      <ConflictAlerts />

      {gitStatus && !isLoading && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="display text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
                Repositories
              </h2>
              <p className="mt-0.5 text-xs text-slate-500">
                {repos.length} workspace{repos.length !== 1 ? 's' : ''} with branch and cleanup context
              </p>
            </div>
          </div>

          <div className="space-y-2">
          {repos.map((repo, i) => (
            <motion.div
              key={repo.path}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.06 + i * 0.04, ease: [0.25, 0.46, 0.45, 0.94] }}
            >
              <ProjectRow repo={repo} />
            </motion.div>
          ))}
          </div>
        </section>
      )}

      {isLoading && (
        <div className="card-elevated flex items-center justify-center py-20">
          <div className="flex items-center gap-2.5 text-sm text-slate-500">
            <RefreshCw className="w-5 h-5 animate-spin text-phosphor-500" />
            Scanning workspaces...
          </div>
        </div>
      )}

      {isError && (
        <div className="card-elevated flex items-center gap-3 border-rose-500/20 bg-rose-500/8 p-4 text-sm text-rose-300">
          <XCircle className="w-5 h-5 text-rose-500 shrink-0" />
          <div>
            <span className="font-medium text-slate-100">Connection failed.</span>{' '}
            Verify the backend is running.
          </div>
        </div>
      )}

      {gitStatus?.repositories.length === 0 && (
        <div className="card-elevated py-20 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-violet-500/15 bg-violet-500/8">
            <GitBranch className="w-7 h-7 text-violet-500/50" />
          </div>
          <p className="mb-1 text-sm font-medium text-slate-300">
            No repositories found
          </p>
          <p className="text-xs text-slate-500">
            Register a project to start tracking its git workspace.
          </p>
        </div>
      )}
    </div>
  )
}
