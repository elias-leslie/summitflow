'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  RotateCcw,
  Shield,
} from 'lucide-react'
import { useState } from 'react'
import {
  fetchSnapshots,
  revertToSnapshot,
  type SnapshotInfo,
} from '@/lib/api/git-enhanced'

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

function SnapshotEntry({ snapshot }: { snapshot: SnapshotInfo }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const revertMut = useMutation({
    mutationFn: () => revertToSnapshot(snapshot.task_id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['git-snapshots'] })
      setConfirming(false)
    },
  })

  const isWorking = revertMut.isPending

  return (
    <div
      className={clsx(
        'flex items-center gap-3 p-3 rounded-lg transition-all',
        snapshot.is_current
          ? 'bg-phosphor-500/5 border border-phosphor-500/20'
          : 'bg-slate-900/20 border border-slate-800/40',
      )}
    >
      {/* Timeline dot */}
      <div className="relative shrink-0">
        <div
          className={clsx(
            'w-3 h-3 rounded-full border-2',
            snapshot.is_current
              ? 'bg-phosphor-500 border-phosphor-500 shadow-[0_0_6px_rgba(0,245,255,0.5)]'
              : 'bg-slate-900 border-slate-600',
          )}
        />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-white truncate">
            {snapshot.task_title || snapshot.task_id}
          </span>
          {snapshot.is_current && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-phosphor-500/15 text-phosphor-400 border border-phosphor-500/20 uppercase shrink-0">
              HEAD
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <span className="font-mono">{snapshot.short_sha}</span>
          <span>{relativeTime(snapshot.created_at)}</span>
          {snapshot.commits_ahead > 0 && (
            <span className="text-amber-500/70">
              {snapshot.commits_ahead} commit{snapshot.commits_ahead !== 1 ? 's' : ''} behind
            </span>
          )}
        </div>
      </div>

      {/* Revert action */}
      {snapshot.commits_ahead > 0 && (
        <div className="shrink-0">
          {confirming ? (
            <div className="flex items-center gap-1.5">
              <button
                disabled={isWorking}
                onClick={() => revertMut.mutate()}
                className={clsx(
                  'px-2 py-1 rounded text-[10px] font-medium transition-all',
                  isWorking
                    ? 'bg-slate-800 text-slate-500'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/30 hover:bg-rose-500/30',
                )}
              >
                {isWorking ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  'Confirm'
                )}
              </button>
              <button
                disabled={isWorking}
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

      {/* Revert result */}
      {revertMut.isSuccess && (
        <span className="text-[9px] font-mono text-emerald-400 shrink-0">Reverted</span>
      )}
      {revertMut.isError && (
        <span className="text-[9px] font-mono text-rose-400 shrink-0">Failed</span>
      )}
    </div>
  )
}

export function SnapshotTimeline() {
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['git-snapshots'],
    queryFn: () => fetchSnapshots(),
    staleTime: 60000,
    refetchInterval: 120000,
  })

  if (isLoading || !data || data.count === 0) return null

  return (
    <section className="animate-in fade-in slide-in-from-top-4 duration-500">
      {/* Section Header — collapsed by default */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between mb-3 group"
      >
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <Shield className="w-5 h-5 text-amber-400" />
            <div className="absolute inset-0 blur-md bg-amber-500/20" />
          </div>
          <h2 className="font-semibold text-white">
            Snapshots
          </h2>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
            {data.count}
          </span>
          {!expanded && (
            <span className="text-[10px] text-slate-600 ml-1">
              Pre-merge safety points
            </span>
          )}
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
        <div className="space-y-1.5 pl-1">
          {data.snapshots.map((snapshot) => (
            <SnapshotEntry key={snapshot.task_id} snapshot={snapshot} />
          ))}
        </div>
      )}
    </section>
  )
}
