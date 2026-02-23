'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ChevronDown,
  ChevronRight,
  GitMerge,
  Minus,
  Plus,
} from 'lucide-react'
import { useState } from 'react'
import {
  fetchRecentMerges,
  fetchTaskDiff,
  type MergedTaskSummary,
} from '@/lib/api/git-enhanced'
import { DiffPanel } from './DiffPanel'

function relativeTime(iso: string): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function StatBar({ additions, deletions }: { additions: number; deletions: number }) {
  const total = additions + deletions
  if (total === 0) return null
  const addPct = Math.max(2, (additions / total) * 100)
  const delPct = Math.max(2, (deletions / total) * 100)

  return (
    <div className="flex items-center gap-1 h-1.5 w-16 rounded-full overflow-hidden bg-slate-800">
      <div
        className="h-full bg-emerald-500 rounded-l-full"
        style={{ width: `${addPct}%` }}
      />
      <div
        className="h-full bg-rose-500 rounded-r-full"
        style={{ width: `${delPct}%` }}
      />
    </div>
  )
}

function MergeRow({ merge }: { merge: MergedTaskSummary }) {
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
          'w-full flex items-center gap-3 p-3 rounded-lg text-left transition-all',
          'bg-slate-900/30 border border-slate-800/60',
          'hover:bg-slate-800/40 hover:border-purple-500/20',
          'hover:shadow-[0_0_15px_rgba(168,85,247,0.08)]',
        )}
      >
        <div className="shrink-0 w-7 h-7 rounded-md bg-purple-500/10 flex items-center justify-center">
          <GitMerge className="w-3.5 h-3.5 text-purple-400" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-sm text-white truncate">{merge.task_title}</div>
          <div className="flex items-center gap-2 text-[10px] text-slate-500">
            <span className="font-mono">{merge.project_id}</span>
            <span>{relativeTime(merge.merged_at)}</span>
          </div>
        </div>

        <div className="shrink-0 flex items-center gap-3">
          <StatBar additions={merge.additions} deletions={merge.deletions} />
          <div className="flex items-center gap-2 text-[10px] font-mono">
            <span className="text-emerald-400 flex items-center gap-0.5">
              <Plus className="w-2.5 h-2.5" />
              {merge.additions}
            </span>
            <span className="text-rose-400 flex items-center gap-0.5">
              <Minus className="w-2.5 h-2.5" />
              {merge.deletions}
            </span>
          </div>
          <span className="text-[10px] text-slate-600">
            {merge.files_changed} file{merge.files_changed !== 1 ? 's' : ''}
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

export function MergedTasksList() {
  const [expanded, setExpanded] = useState(true)

  const { data, isLoading } = useQuery({
    queryKey: ['recent-merges'],
    queryFn: () => fetchRecentMerges(20),
    staleTime: 60000,
    refetchInterval: 120000,
  })

  if (isLoading || !data || data.count === 0) return null

  return (
    <section className="animate-in fade-in slide-in-from-top-4 duration-500">
      {/* Section Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between mb-3 group"
      >
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <GitMerge className="w-5 h-5 text-purple-400" />
            <div className="absolute inset-0 blur-md bg-purple-500/30" />
          </div>
          <h2 className="font-semibold text-white">
            Merged Tasks
          </h2>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">
            {data.count}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-slate-500 group-hover:text-slate-300 transition-colors">
          <span className="text-[10px] uppercase tracking-wider">
            {expanded ? 'Collapse' : 'Expand'}
          </span>
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="space-y-1.5">
          {data.merges.map((merge) => (
            <MergeRow key={merge.task_id} merge={merge} />
          ))}
        </div>
      )}
    </section>
  )
}
