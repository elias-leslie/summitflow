'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle,
  FileWarning,
  GitBranch,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react'
import {
  dismissConflict,
  fetchConflicts,
  retryMerge,
  type ConflictInfo,
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

function ConflictCard({ conflict }: { conflict: ConflictInfo }) {
  const queryClient = useQueryClient()

  const retryMut = useMutation({
    mutationFn: () => retryMerge(conflict.task_id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['git-conflicts'] }),
  })

  const dismissMut = useMutation({
    mutationFn: () => dismissConflict(conflict.task_id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['git-conflicts'] }),
  })

  const isWorking = retryMut.isPending || dismissMut.isPending

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-lg border transition-all duration-300',
        'bg-gradient-to-br from-rose-950/40 to-slate-900/80',
        'border-rose-500/30',
        'hover:border-rose-500/50 hover:shadow-[0_0_20px_rgba(244,63,94,0.15)]',
      )}
    >
      {/* Hazard stripe top edge */}
      <div
        className="h-0.5 w-full"
        style={{
          background: `repeating-linear-gradient(
            90deg,
            #f43f5e 0px,
            #f43f5e 8px,
            transparent 8px,
            transparent 12px
          )`,
        }}
      />

      <div className="p-4">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="relative shrink-0 w-8 h-8 rounded-md bg-rose-500/15 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              {/* Pulse indicator */}
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-rose-500 animate-pulse shadow-[0_0_6px_rgba(244,63,94,0.8)]" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white truncate">
                {conflict.task_title}
              </h3>
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <GitBranch className="w-3 h-3 shrink-0" />
                <span className="font-mono text-rose-400/70 truncate">
                  {conflict.task_branch}
                </span>
                <span className="text-slate-600 shrink-0">
                  {relativeTime(conflict.detected_at)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Conflicting files */}
        <div className="mb-3 p-2.5 rounded-md bg-black/30 border border-rose-500/10">
          <div className="flex items-center gap-1.5 mb-1.5">
            <FileWarning className="w-3 h-3 text-rose-500/60" />
            <span className="text-[10px] text-rose-400/60 uppercase tracking-wider font-medium">
              {conflict.conflicting_files.length} Conflicting File{conflict.conflicting_files.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="space-y-0.5">
            {conflict.conflicting_files.slice(0, 5).map((file) => (
              <div
                key={file}
                className="text-xs font-mono text-slate-400 truncate pl-1 border-l-2 border-rose-500/30"
              >
                {file}
              </div>
            ))}
            {conflict.conflicting_files.length > 5 && (
              <div className="text-[10px] text-slate-600 pl-1">
                +{conflict.conflicting_files.length - 5} more
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            disabled={isWorking}
            onClick={() => retryMut.mutate()}
            className={clsx(
              'flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
              isWorking
                ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                : 'bg-rose-500/15 text-rose-300 border border-rose-500/30 hover:bg-rose-500/25 hover:border-rose-500/50 hover:shadow-[0_0_10px_rgba(244,63,94,0.2)]',
            )}
          >
            {retryMut.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3" />
            )}
            Retry Merge
          </button>
          <button
            disabled={isWorking}
            onClick={() => dismissMut.mutate()}
            className={clsx(
              'flex items-center justify-center gap-1 px-3 py-1.5 rounded-md text-xs transition-all',
              isWorking
                ? 'text-slate-600 cursor-not-allowed'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
            )}
          >
            <X className="w-3 h-3" />
            Dismiss
          </button>
        </div>

        {/* Retry result feedback */}
        {retryMut.isSuccess && (
          <div className="mt-2 text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded border border-emerald-500/20">
            Merge retry completed
          </div>
        )}
        {retryMut.isError && (
          <div className="mt-2 text-[10px] font-mono text-rose-400 bg-rose-500/10 px-2 py-1 rounded border border-rose-500/20">
            Retry failed — conflict may still exist
          </div>
        )}
      </div>
    </div>
  )
}

export function ConflictAlerts() {
  const { data, isLoading } = useQuery({
    queryKey: ['git-conflicts'],
    queryFn: fetchConflicts,
    staleTime: 15000,
    refetchInterval: 30000,
  })

  // Only render when conflicts exist
  if (isLoading || !data || data.count === 0) return null

  return (
    <section className="animate-in fade-in slide-in-from-top-4 duration-500">
      {/* Section Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <AlertTriangle className="w-5 h-5 text-rose-400" />
            <div className="absolute inset-0 blur-md bg-rose-500/40" />
          </div>
          <h2 className="font-semibold text-white">
            Merge Conflicts
          </h2>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-400 border border-rose-500/30">
            {data.count}
          </span>
        </div>
      </div>

      {/* Conflict Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {data.conflicts.map((conflict) => (
          <ConflictCard key={conflict.task_id} conflict={conflict} />
        ))}
      </div>
    </section>
  )
}
