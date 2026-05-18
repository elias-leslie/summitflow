import clsx from 'clsx'
import { GitBranch } from 'lucide-react'
import type { CheckpointInfo } from '@/lib/api/git-enhanced'

export function CheckpointCompact({
  checkpoint,
}: {
  checkpoint: CheckpointInfo
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-md bg-slate-900/40 border border-slate-800/50 hover:border-phosphor-500/20 transition-colors">
      <div className="relative shrink-0">
        <GitBranch className="w-4 h-4 text-phosphor-500" />
        {checkpoint.is_active && (
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-phosphor-500 shadow-[0_0_6px_rgba(0,245,255,0.6)]" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-sm font-semibold text-slate-100">
          {checkpoint.task_id}
        </span>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <span className="font-mono text-violet-300">
            base: {checkpoint.base_branch}
          </span>
        </div>
      </div>
      <span
        className={clsx(
          'text-[9px] font-mono px-1.5 py-0.5 rounded border shrink-0',
          checkpoint.is_active
            ? 'bg-phosphor-500/10 text-phosphor-400 border-phosphor-500/20'
            : 'bg-slate-800/50 text-slate-500 border-slate-700/50',
        )}
      >
        {checkpoint.is_active ? 'ACTIVE' : 'IDLE'}
      </span>
    </div>
  )
}
