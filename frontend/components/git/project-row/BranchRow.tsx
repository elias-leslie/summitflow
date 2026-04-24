import clsx from 'clsx'
import { GitBranch } from 'lucide-react'
import type { BranchInfo } from '@/lib/api/git-enhanced'
import { formatTimeAgo } from '@/lib/format'

function BranchBadge({
  label,
  tone,
}: {
  label: string
  tone: 'cyan' | 'amber' | 'emerald' | 'rose'
}) {
  const tones = {
    cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    rose: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  }

  return (
    <span
      className={clsx(
        'rounded-full border px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wide',
        tones[tone],
      )}
    >
      {label}
    </span>
  )
}

function orphanBadge(branch: BranchInfo) {
  switch (branch.cleanup_resolution) {
    case 'prunable':
    case 'equivalent':
      return <BranchBadge label="Prunable" tone="emerald" />
    case 'salvage':
      return <BranchBadge label="Salvage" tone="rose" />
    case 'review':
      return <BranchBadge label="Review" tone="amber" />
    default:
      return <BranchBadge label="Orphan" tone="amber" />
  }
}

export function BranchRow({ branch }: { branch: BranchInfo }) {
  const isTaskOrphan = Boolean(branch.task_id && !branch.has_checkpoint)
  const orphanFacts = [
    branch.task_status ? `task ${branch.task_status}` : null,
    branch.commits_ahead != null ? `${branch.commits_ahead} ahead` : null,
    branch.commits_behind != null && branch.commits_behind > 0
      ? `${branch.commits_behind} behind`
      : null,
    branch.files_changed != null ? `${branch.files_changed} files` : null,
    branch.has_node_modules_artifact ? 'node_modules residue' : null,
  ].filter(Boolean)

  return (
    <div className="rounded-md border border-slate-800/50 bg-slate-900/30 px-3 py-2">
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 shrink-0 rounded bg-cyan-500/10 p-1.5">
          <GitBranch className="h-3 w-3 text-cyan-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm text-slate-100">
              {branch.name}
            </span>
            {branch.is_current && (
              <BranchBadge label="Current" tone="emerald" />
            )}
            {branch.has_checkpoint && (
              <BranchBadge label="Checkpoint" tone="cyan" />
            )}
            {isTaskOrphan && orphanBadge(branch)}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
            {branch.last_commit_short && (
              <span className="font-mono text-cyan-300">
                {branch.last_commit_short}
              </span>
            )}
            {branch.last_commit_date && (
              <span>{formatTimeAgo(branch.last_commit_date)}</span>
            )}
            {branch.task_id && (
              <span className="font-mono">{branch.task_id}</span>
            )}
            {isTaskOrphan && orphanFacts.length > 0 && (
              <span className="text-amber-300/80">
                {orphanFacts.join(' / ')}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
