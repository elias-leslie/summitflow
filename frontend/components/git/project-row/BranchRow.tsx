import clsx from 'clsx'
import { GitBranch } from 'lucide-react'
import type { BranchInfo } from '@/lib/api/git-enhanced'
import { formatTimeAgo } from '@/lib/format'

function BranchBadge({
  label,
  tone,
}: {
  label: string
  tone: 'cyan' | 'amber' | 'emerald'
}) {
  const tones = {
    cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
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

export function BranchRow({ branch }: { branch: BranchInfo }) {
  const isTaskOrphan = Boolean(branch.task_id && !branch.has_checkpoint)

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
            {isTaskOrphan && <BranchBadge label="Orphan" tone="amber" />}
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
          </div>
        </div>
      </div>
    </div>
  )
}
