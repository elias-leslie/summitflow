import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { GitMerge, Minus, Plus } from 'lucide-react'
import { useState } from 'react'
import { fetchTaskDiff, type MergedTaskSummary } from '@/lib/api/git-enhanced'
import { DiffPanel } from '../DiffPanel'
import { formatTimeAgo } from '@/lib/format'
import { StatBar } from './StatBar'

export function MergeRow({ merge }: { merge: MergedTaskSummary }) {
  const [diffOpen, setDiffOpen] = useState(false)

  const { data: diffData } = useQuery({
    queryKey: ['task-diff', merge.task_id],
    queryFn: () => fetchTaskDiff(merge.task_id),
    enabled: diffOpen,
    staleTime: 300000,
  })

  return (
    <>
      <button
        onClick={() => setDiffOpen(true)}
        className={clsx(
          'w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-left transition-all',
          'bg-slate-900/30 border border-slate-800/50',
          'hover:bg-slate-800/40 hover:border-purple-500/20',
        )}
      >
        <GitMerge className="w-3.5 h-3.5 text-purple-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-sm text-white truncate block">{merge.task_title}</span>
          <span className="text-[10px] text-slate-500">{formatTimeAgo(merge.merged_at)}</span>
        </div>
        <div className="shrink-0 flex items-center gap-2.5">
          <StatBar additions={merge.additions} deletions={merge.deletions} />
          <span className="text-[10px] font-mono text-emerald-400 flex items-center gap-0.5">
            <Plus className="w-2.5 h-2.5" />{merge.additions}
          </span>
          <span className="text-[10px] font-mono text-rose-400 flex items-center gap-0.5">
            <Minus className="w-2.5 h-2.5" />{merge.deletions}
          </span>
        </div>
      </button>
      {diffData && (
        <DiffPanel
          open={diffOpen}
          onClose={() => setDiffOpen(false)}
          title={merge.task_title}
          subtitle={`${merge.task_id} | ${merge.project_id}`}
          files={diffData.files}
          stats={diffData.stats}
        />
      )}
    </>
  )
}
