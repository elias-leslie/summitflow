'use client'

import { clsx } from 'clsx'
import { Camera, Loader2, Scissors, Timer } from 'lucide-react'
import { useState } from 'react'
import {
  type BtrfsSummary,
  createSnapshot,
  pruneSnapshots,
} from '@/lib/api/snapshots'
import { formatBytes } from '@/lib/format'

interface SnapshotSummaryCardProps {
  summary: BtrfsSummary | undefined
  isLoading: boolean
  onMutated: () => void
}

export function SnapshotSummaryCard({
  summary,
  isLoading,
  onMutated,
}: SnapshotSummaryCardProps) {
  const [snapping, setSnapping] = useState(false)
  const [pruning, setPruning] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)

  if (isLoading || !summary) return null

  const autoCount = Object.entries(summary.by_source)
    .filter(([k]) => k.startsWith('auto'))
    .reduce((sum, [, v]) => sum + v, 0)
  const manualCount = summary.by_source.manual ?? 0

  const handleSnap = async () => {
    setSnapping(true)
    setFeedback(null)
    try {
      const snap = await createSnapshot('summitflow')
      setFeedback(`Snapshot ${snap.name ?? snap.id.slice(0, 16)} created`)
      onMutated()
      setTimeout(() => setFeedback(null), 3000)
    } catch {
      setFeedback('Snapshot failed')
    }
    setSnapping(false)
  }

  const handlePrune = async () => {
    setPruning(true)
    setFeedback(null)
    try {
      const result = await pruneSnapshots(false)
      setFeedback(
        result.ok ? `Pruned ${result.pruned} snapshot(s)` : 'Prune failed',
      )
      onMutated()
      setTimeout(() => setFeedback(null), 3000)
    } catch {
      setFeedback('Prune failed')
    }
    setPruning(false)
  }

  const timerActive = summary.autosnap_timer_active

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 overflow-hidden',
        timerActive ? 'border-l-emerald-500' : 'border-l-slate-600',
      )}
    >
      {/* Header */}
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Camera className="w-4 h-4 text-slate-500" />
          <span className="text-sm font-medium text-slate-100">
            Btrfs Snapshots
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={clsx(
              'w-1.5 h-1.5 rounded-full',
              timerActive ? 'bg-emerald-500' : 'bg-slate-600',
            )}
          />
          <div className="flex items-center gap-1 text-[10px] text-slate-500">
            <Timer className="w-3 h-3" />
            {timerActive ? 'Autosnap active' : 'Timer inactive'}
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="border-t border-slate-800/40 px-4 py-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Total
            </div>
            <div className="text-xs text-slate-200">
              {summary.total_snapshots} snapshots
            </div>
          </div>
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Exclusive
            </div>
            <div className="text-xs text-slate-200 font-mono">
              {formatBytes(summary.total_usage_bytes)}
            </div>
          </div>
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Scopes
            </div>
            <div className="text-xs text-slate-200">
              {summary.active_scope_count} active
              {summary.archived_scope_count > 0
                ? ` / ${summary.archived_scope_count} archived`
                : ''}
            </div>
          </div>
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Sources
            </div>
            <div className="text-xs text-slate-200">
              {manualCount} manual, {autoCount} auto
            </div>
          </div>
        </div>

        {/* Policy summary */}
        <div className="mt-2 text-[10px] text-slate-600 leading-relaxed">
          Projects: every {Math.round(summary.policy.interval_minutes / 60)}h,
          keep {summary.policy.auto_keep_per_scope}
        </div>
        <div className="mt-1 text-[10px] text-slate-600 leading-relaxed">
          Archived auto scopes: keep {summary.policy.archived_keep_per_project}{' '}
          recent scope
          {summary.policy.archived_keep_per_project === 1 ? '' : 's'} per
          project, {summary.policy.archived_auto_keep_per_scope} auto snapshot
          {summary.policy.archived_auto_keep_per_scope === 1 ? '' : 's'} each
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 mt-3">
          <button
            type="button"
            onClick={handleSnap}
            disabled={snapping}
            className="flex items-center gap-1.5 text-2xs px-2.5 py-1 rounded bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20 disabled:opacity-40 transition-colors"
          >
            {snapping ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Camera className="w-3 h-3" />
            )}
            Take Snapshot
          </button>
          <button
            type="button"
            onClick={handlePrune}
            disabled={pruning}
            className="flex items-center gap-1.5 text-2xs px-2.5 py-1 rounded bg-slate-700/40 text-slate-400 hover:bg-slate-700/60 disabled:opacity-40 transition-colors"
          >
            {pruning ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Scissors className="w-3 h-3" />
            )}
            Prune
          </button>
          {feedback && (
            <span className="text-2xs text-emerald-400">{feedback}</span>
          )}
        </div>
      </div>
    </div>
  )
}
