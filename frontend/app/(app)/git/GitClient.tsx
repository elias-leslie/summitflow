'use client'

import clsx from 'clsx'
import {
  AlertTriangle,
  GitBranch,
  Layers,
  ShieldCheck,
  RefreshCw,
  Scissors,
  XCircle,
} from 'lucide-react'
import { motion } from 'motion/react'
import { ConflictAlerts } from '@/components/git/ConflictAlerts'
import { ProjectRow } from '@/components/git/ProjectRow'
import { useGitStatus } from './useGitStatus'

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
  const repos = gitStatus?.repositories ?? []

  const dirtyRepos = repos.filter(
    (r) => r.state === 'dirty' || r.state === 'ahead',
  ).length
  const activeWorktrees = repos.reduce(
    (s, r) => s + (r.workspace_summary?.active_worktrees ?? 0),
    0,
  )
  const dirtyWorktrees = repos.reduce(
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
  const hasIssues =
    dirtyRepos + dirtyWorktrees + orphanBranches + prunableBranches > 0
  const cleanRepos = Math.max(repos.length - dirtyRepos, 0)
  const reviewDebt = orphanBranches + prunableBranches
  const statCards = [
    {
      icon: ShieldCheck,
      label: 'Clean repos',
      value: cleanRepos,
      detail: 'ready for normal work',
      tone: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200',
    },
    {
      icon: AlertTriangle,
      label: 'Dirty repos',
      value: dirtyRepos,
      detail: 'local changes or ahead branches',
      tone: 'border-rose-500/20 bg-rose-500/10 text-rose-200',
    },
    {
      icon: Layers,
      label: 'Active worktrees',
      value: activeWorktrees,
      detail: `${dirtyWorktrees} have local edits`,
      tone: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200',
    },
    {
      icon: Scissors,
      label: 'Cleanup debt',
      value: reviewDebt,
      detail: 'orphan + prunable branches',
      tone: 'border-amber-500/20 bg-amber-500/10 text-amber-200',
    },
  ]

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 px-4 py-5 md:px-5 lg:px-6">
      <motion.section
        {...fadeUp}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="panel-glass px-4 py-4 md:px-5"
      >
        <div className="space-y-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-outrun-500/20 bg-outrun-500/10">
                <GitBranch className="h-5 w-5 text-outrun-400" />
              </div>
              <div>
                <div className="eyebrow">Repository operations</div>
                <h1 className="display mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 lg:text-3xl">
                  Git control surface
                </h1>
                <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-300">
                  Keep repo hygiene visible, then drop into the workspace list
                  without wasting the first screen on oversized summary cards.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {gitStatus && !isLoading && hasIssues ? (
                <>
                  <StatPill
                    icon={AlertTriangle}
                    value={dirtyRepos}
                    label="dirty"
                    tone="bg-pink-500/8 text-pink-300 border-pink-500/20"
                  />
                  <StatPill
                    icon={Layers}
                    value={activeWorktrees}
                    label="worktrees"
                    tone="bg-phosphor-500/8 text-phosphor-300 border-phosphor-500/20"
                  />
                  <StatPill
                    icon={Scissors}
                    value={reviewDebt}
                    label="cleanup"
                    tone="bg-amber-500/8 text-amber-300 border-amber-500/20"
                  />
                </>
              ) : (
                <div className="rounded-full border border-emerald-500/18 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-200">
                  No active repo hygiene warnings are visible right now.
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {statCards.map((card) => {
              const Icon = card.icon
              return (
                <div
                  key={card.label}
                  className={clsx('rounded-[1.15rem] border px-3.5 py-3', card.tone)}
                >
                  <div className="flex items-center gap-3">
                    <div className="rounded-xl border border-white/10 bg-slate-950/45 p-2">
                      <Icon className="h-4 w-4 text-current" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-mono text-xl font-semibold leading-none tabular-nums text-slate-50">
                        {card.value}
                      </div>
                      <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                        {card.label}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400">
                        {card.detail}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </motion.section>

      <ConflictAlerts />

      {gitStatus && !isLoading && (
        <section className="space-y-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="eyebrow">Repositories</div>
              <h2 className="display mt-1.5 text-xl font-semibold text-slate-100">
                Workspace inventory
              </h2>
              <p className="mt-1.5 text-sm text-slate-400">
                {repos.length} workspace{repos.length !== 1 ? 's' : ''} with
                live branch, sync, and cleanup context.
              </p>
            </div>
          </div>

          <div className="space-y-3">
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
