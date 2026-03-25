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

  return (
    <div className="p-6 space-y-5 max-w-6xl mx-auto">
      {/* Header */}
      <motion.header
        {...fadeUp}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="flex items-center justify-between gap-4 hero-glow"
      >
        <div className="flex items-center gap-3 relative z-10">
          <div className="p-1.5 rounded-md bg-outrun-500/10 border border-outrun-500/20">
            <GitBranch className="w-5 h-5 text-outrun-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-100 display tracking-tight leading-none">
              Git Operations
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              {repos.length} workspace{repos.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>

      </motion.header>

      {/* Conflict Alerts */}
      <ConflictAlerts />

      {/* Compact status strip — only renders when issues exist */}
      {gitStatus && !isLoading && hasIssues && (
        <div className="flex flex-wrap items-center gap-2">
          <StatPill
            icon={AlertTriangle}
            value={dirtyRepos}
            label="dirty"
            tone="bg-pink-500/8 text-pink-400 border-pink-500/20"
          />
          <StatPill
            icon={Layers}
            value={activeWorktrees}
            label="worktrees"
            tone="bg-phosphor-500/8 text-phosphor-400 border-phosphor-500/20"
          />
          <StatPill
            icon={AlertTriangle}
            value={dirtyWorktrees}
            label="dirty wt"
            tone="bg-orange-500/8 text-orange-400 border-orange-500/20"
          />
          <StatPill
            icon={Unplug}
            value={orphanBranches}
            label="orphan"
            tone="bg-amber-500/8 text-amber-400 border-amber-500/20"
          />
          <StatPill
            icon={Scissors}
            value={prunableBranches}
            label="prunable"
            tone="bg-rose-500/8 text-rose-400 border-rose-500/20"
          />
        </div>
      )}

      {/* Repository list */}
      {gitStatus && !isLoading && (
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
      )}

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <div className="flex items-center gap-2.5 text-slate-500 text-sm">
            <RefreshCw className="w-5 h-5 animate-spin text-phosphor-500" />
            Scanning workspaces...
          </div>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="p-4 rounded-lg bg-rose-500/8 border border-rose-500/20 text-rose-300 flex items-center gap-3 text-sm">
          <XCircle className="w-5 h-5 text-rose-500 shrink-0" />
          <div>
            <span className="font-medium text-slate-100">Connection failed.</span>{' '}
            Verify the backend is running.
          </div>
        </div>
      )}

      {/* Empty */}
      {gitStatus?.repositories.length === 0 && (
        <div className="text-center py-20">
          <div className="mx-auto mb-4 w-14 h-14 rounded-2xl bg-violet-500/8 border border-violet-500/15 flex items-center justify-center">
            <GitBranch className="w-7 h-7 text-violet-500/50" />
          </div>
          <p className="text-sm font-medium text-slate-400 mb-1">No repositories found</p>
          <p className="text-xs text-slate-600">Register a project to start tracking its git workspace.</p>
        </div>
      )}
    </div>
  )
}
