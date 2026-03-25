'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Layers,
  Loader2,
  Scissors,
  Sparkles,
  Unplug,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { getStateInfo } from '@/app/(app)/git/utils'
import { type RepoStatus, smartSyncProject } from '@/lib/api'
import { DashboardContent } from './project-row/DashboardContent'
import { SyncResultBlock } from './project-row/SyncResultBlock'

interface ProjectRowProps {
  repo: RepoStatus
}

const SYNC_RESULT_AUTO_DISMISS_MS = 12000

export function ProjectRow({ repo }: ProjectRowProps) {
  const [expanded, setExpanded] = useState(false)
  const [syncResult, setSyncResult] = useState<Awaited<
    ReturnType<typeof smartSyncProject>
  > | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon
  const queryClient = useQueryClient()
  const workspaceSummary = repo.workspace_summary
  const repoKey = repo.project_id ?? repo.name

  const syncMutation = useMutation({
    mutationFn: () => smartSyncProject(repoKey),
    onMutate: () => {
      setSyncResult(null)
    },
    onSuccess: (result) => {
      setSyncResult(result)
      queryClient.invalidateQueries({ queryKey: ['git-status'] })
      queryClient.invalidateQueries({
        queryKey: ['project-dashboard', repoKey],
      })
    },
    onError: () => {
      setSyncResult(null)
    },
  })

  useEffect(() => {
    if (!syncResult) return undefined
    const id = window.setTimeout(() => setSyncResult(null), SYNC_RESULT_AUTO_DISMISS_MS)
    return () => window.clearTimeout(id)
  }, [syncResult])

  const wsBadges: Array<{
    icon: typeof Layers
    count: number
    label: string
    tone: string
  }> = []
  if (workspaceSummary) {
    if (workspaceSummary.active_worktrees > 0)
      wsBadges.push({
        icon: Layers,
        count: workspaceSummary.active_worktrees,
        label: 'wt',
        tone: 'text-phosphor-400',
      })
    if (workspaceSummary.dirty_worktrees > 0)
      wsBadges.push({
        icon: AlertTriangle,
        count: workspaceSummary.dirty_worktrees,
        label: 'dirty',
        tone: 'text-rose-400',
      })
    if (workspaceSummary.orphan_branches > 0)
      wsBadges.push({
        icon: Unplug,
        count: workspaceSummary.orphan_branches,
        label: 'orphan',
        tone: 'text-amber-400',
      })
    if (workspaceSummary.prunable_branches > 0)
      wsBadges.push({
        icon: Scissors,
        count: workspaceSummary.prunable_branches,
        label: 'prune',
        tone: 'text-rose-400',
      })
  }

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl border transition-all duration-200',
        'bg-slate-950/45',
        expanded
          ? 'border-slate-700/90'
          : 'border-slate-800/60 hover:border-slate-700/60',
      )}
    >
      <div
        className={clsx(
          'absolute left-0 top-0 bottom-0 w-[3px] rounded-l-[1.6rem] transition-colors duration-200',
          stateInfo.stripColor ?? 'bg-transparent',
        )}
        aria-hidden="true"
      />

      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
        aria-expanded={expanded}
        className="group cursor-pointer select-none px-4 py-3 transition-colors duration-150 hover:bg-slate-900/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500/40"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <ChevronRight
                className={clsx(
                  'h-3.5 w-3.5 shrink-0 text-slate-600 transition-all duration-200 group-hover:text-slate-400',
                  expanded && 'rotate-90',
                )}
              />
              <span className="text-base font-semibold tracking-tight text-slate-100">
                {repo.name}
              </span>
              <span
                className={clsx(
                  'flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] uppercase tracking-[0.16em]',
                  stateInfo.bg,
                  stateInfo.color,
                )}
              >
                <StateIcon className="h-3 w-3" />
                {stateInfo.label}
                {repo.state === 'dirty' && repo.uncommitted > 0 && (
                  <span className="opacity-70">({repo.uncommitted})</span>
                )}
              </span>
              {repo.ahead > 0 && (
                <span className="flex items-center gap-1 rounded-full border border-cyan-500/18 bg-cyan-500/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-phosphor-300">
                  <ArrowUp className="h-3 w-3" />
                  {repo.ahead} ahead
                </span>
              )}
              {repo.behind > 0 && (
                <span className="flex items-center gap-1 rounded-full border border-amber-500/18 bg-amber-500/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-amber-300">
                  <ArrowDown className="h-3 w-3" />
                  {repo.behind} behind
                </span>
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-slate-700/70 bg-slate-950/75 px-2.5 py-1 font-mono text-[11px] text-slate-400">
                {repo.branch}
              </span>
              {repo.project_id ? (
                <span className="rounded-full border border-slate-700/70 bg-slate-950/75 px-2.5 py-1 text-[11px] text-slate-500">
                  {repo.project_id}
                </span>
              ) : null}
              {wsBadges.map((b) => (
                <span
                  key={b.label}
                  className={clsx(
                    'inline-flex items-center gap-1 rounded-full border border-slate-700/70 bg-slate-950/75 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em]',
                    b.tone,
                  )}
                  title={`${b.count} ${b.label}`}
                >
                  <b.icon className="h-3 w-3" />
                  {b.count} {b.label}
                </span>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3 lg:ml-4">
            <button
              type="button"
              disabled={syncMutation.isPending}
              onClick={(e) => {
                e.stopPropagation()
                syncMutation.mutate()
              }}
              className={clsx(
                'inline-flex items-center gap-2 rounded-2xl border px-4 py-2 text-xs font-medium transition-all',
                syncMutation.isPending
                  ? 'cursor-not-allowed border-slate-800 bg-slate-900 text-slate-500'
                  : 'border-outrun-500/20 bg-outrun-500/12 text-outrun-300 hover:border-outrun-500/40 hover:bg-outrun-500/20',
              )}
            >
              {syncMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              {syncMutation.isPending ? 'Syncing' : 'Smart Sync'}
            </button>
          </div>
        </div>
      </div>

      {syncResult && (
        <div className="px-5 pb-3">
          <SyncResultBlock result={syncResult} />
        </div>
      )}

      <div
        ref={contentRef}
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-5 py-4">
            <DashboardContent projectId={repoKey} />
          </div>
        </div>
      </div>
    </div>
  )
}
