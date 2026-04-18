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
  type ConflictInfo,
  dismissConflict,
  fetchConflicts,
  retryMerge,
} from '@/lib/api/git-enhanced'
import { formatTimeAgo } from '@/lib/format'
import { POLL_STANDARD, STALE_STANDARD } from '@/lib/polling'

function ConflictCard({ conflict }: { conflict: ConflictInfo }) {
  const queryClient = useQueryClient()

  const retryMut = useMutation({
    mutationFn: () => retryMerge(conflict.task_id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['git-conflicts'] })
      queryClient.invalidateQueries({
        queryKey: ['project-dashboard', conflict.project_id],
      })
    },
  })

  const dismissMut = useMutation({
    mutationFn: () => dismissConflict(conflict.task_id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['git-conflicts'] })
      queryClient.invalidateQueries({
        queryKey: ['project-dashboard', conflict.project_id],
      })
    },
  })

  const isWorking = retryMut.isPending || dismissMut.isPending

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-[1.6rem] border transition-all duration-300',
        'bg-gradient-to-br from-rose-950/40 to-slate-950/80',
        'border-rose-500/30',
        'hover:border-rose-500/50 hover:shadow-[0_0_24px_rgba(244,63,94,0.18)]',
      )}
    >
      <div
        className="h-1 w-full"
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

      <div className="p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-rose-500/20 bg-rose-500/15">
              <AlertTriangle className="h-4 w-4 text-rose-400" />
              <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-rose-500 animate-pulse shadow-[0_0_6px_rgba(244,63,94,0.8)]" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-slate-100">
                {conflict.task_title}
              </h3>
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <GitBranch className="h-3 w-3 shrink-0" />
                <span className="truncate font-mono text-rose-300/70">
                  {conflict.task_branch}
                </span>
                <span className="text-slate-600 shrink-0">
                  {formatTimeAgo(conflict.detected_at)}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="mb-4 rounded-[1.2rem] border border-rose-500/10 bg-slate-950/30 p-3">
          <div className="mb-1.5 flex items-center gap-1.5">
            <FileWarning className="h-3 w-3 text-rose-500/60" />
            <span className="text-[10px] font-medium uppercase tracking-wider text-rose-300/70">
              {conflict.conflicting_files.length} Conflicting File
              {conflict.conflicting_files.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="space-y-0.5">
            {conflict.conflicting_files.slice(0, 5).map((file) => (
              <div
                key={file}
                className="truncate border-l-2 border-rose-500/30 pl-2 font-mono text-xs text-slate-400"
              >
                {file}
              </div>
            ))}
            {conflict.conflicting_files.length > 5 && (
              <div className="pl-2 text-[10px] text-slate-600">
                +{conflict.conflicting_files.length - 5} more
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={isWorking}
            onClick={() => retryMut.mutate()}
            className={clsx(
              'flex flex-1 items-center justify-center gap-1.5 rounded-2xl border px-3 py-2 text-xs font-medium transition-all',
              isWorking
                ? 'cursor-not-allowed border-slate-800 bg-slate-800 text-slate-500'
                : 'border-rose-500/30 bg-rose-500/15 text-rose-200 hover:border-rose-500/50 hover:bg-rose-500/25 hover:shadow-[0_0_10px_rgba(244,63,94,0.2)]',
            )}
          >
            {retryMut.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            Retry Merge
          </button>
          <button
            type="button"
            disabled={isWorking}
            onClick={() => dismissMut.mutate()}
            className={clsx(
              'flex items-center justify-center gap-1 rounded-2xl border border-slate-800/70 px-3 py-2 text-xs transition-all',
              isWorking
                ? 'text-slate-600 cursor-not-allowed'
                : 'text-slate-500 hover:border-slate-700 hover:bg-slate-800/50 hover:text-slate-300',
            )}
          >
            <X className="h-3 w-3" />
            Dismiss
          </button>
        </div>

        {retryMut.isSuccess && (
          <div className="mt-3 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-[10px] font-mono text-emerald-300">
            Merge retry completed
          </div>
        )}
        {retryMut.isError && (
          <div className="mt-3 rounded-full border border-rose-500/20 bg-rose-500/10 px-3 py-1 text-[10px] font-mono text-rose-300">
            Retry failed — conflict may still exist
          </div>
        )}
      </div>
    </div>
  )
}

export function ConflictAlerts({ projectId }: { projectId?: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['git-conflicts', projectId ?? 'all'],
    queryFn: () => fetchConflicts(projectId),
    staleTime: STALE_STANDARD,
    refetchInterval: POLL_STANDARD * 2,
  })

  // Only render when conflicts exist
  if (isLoading || !data || data.count === 0) return null

  return (
    <section className="animate-in fade-in slide-in-from-top-4 space-y-4 duration-500">
      <div className="card-elevated px-4 py-3">
        <div className="flex items-center gap-2.5">
          <AlertTriangle className="h-4 w-4 text-rose-400" />
          <div>
            <h2 className="text-sm font-semibold text-slate-100">
              Merge Conflicts
            </h2>
            <p className="text-xs text-slate-400">
              {data.count} conflict{data.count !== 1 ? 's' : ''} blocking merge
              completion
            </p>
          </div>
          <span className="ml-auto rounded-full border border-rose-500/30 bg-rose-500/15 px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.14em] text-rose-300">
            {data.count} active
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {data.conflicts.map((conflict) => (
          <ConflictCard key={conflict.task_id} conflict={conflict} />
        ))}
      </div>
    </section>
  )
}
