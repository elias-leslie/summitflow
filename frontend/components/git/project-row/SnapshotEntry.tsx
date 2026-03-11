import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Loader2, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { revertToSnapshot, type SnapshotInfo } from '@/lib/api/git-enhanced'
import { formatTimeAgo } from '@/lib/format'

export function SnapshotEntry({ snapshot }: { snapshot: SnapshotInfo }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const revertMut = useMutation({
    mutationFn: () => revertToSnapshot(snapshot.task_id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['project-dashboard', snapshot.project_id] })
      setConfirming(false)
    },
  })

  return (
    <div
      className={clsx(
        'flex items-center gap-3 px-3 py-2 rounded-md transition-all',
        snapshot.is_current
          ? 'bg-phosphor-500/5 border border-phosphor-500/20'
          : 'bg-slate-900/20 border border-slate-800/40',
      )}
    >
      <div
        className={clsx(
          'w-2.5 h-2.5 rounded-full border-2 shrink-0',
          snapshot.is_current
            ? 'bg-phosphor-500 border-phosphor-500 shadow-[0_0_6px_rgba(0,245,255,0.5)]'
            : 'bg-slate-900 border-slate-600',
        )}
      />
      <div className="flex-1 min-w-0">
        <span className="text-sm text-white truncate block">{snapshot.task_title || snapshot.task_id}</span>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <span className="font-mono">{snapshot.short_sha}</span>
          <span>{formatTimeAgo(snapshot.created_at)}</span>
          {snapshot.commits_ahead > 0 && (
            <span className="text-amber-500/70">{snapshot.commits_ahead} behind</span>
          )}
        </div>
      </div>
      {snapshot.commits_ahead > 0 && (
        <div className="shrink-0">
          {confirming ? (
            <div className="flex items-center gap-1.5">
              <button
                disabled={revertMut.isPending}
                onClick={() => revertMut.mutate()}
                className={clsx(
                  'px-2 py-1 rounded text-[10px] font-medium transition-all',
                  revertMut.isPending
                    ? 'bg-slate-800 text-slate-500'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/30 hover:bg-rose-500/30',
                )}
              >
                {revertMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Confirm'}
              </button>
              <button
                disabled={revertMut.isPending}
                onClick={() => setConfirming(false)}
                className="px-2 py-1 rounded text-[10px] text-slate-500 hover:text-slate-300"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 transition-all"
            >
              <RotateCcw className="w-3 h-3" />
              Revert
            </button>
          )}
        </div>
      )}
      {revertMut.isSuccess && <span className="text-[9px] font-mono text-emerald-400 shrink-0">Reverted</span>}
      {revertMut.isError && <span className="text-[9px] font-mono text-rose-400 shrink-0">Failed</span>}
    </div>
  )
}
