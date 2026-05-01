'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle,
  ArrowDown,
  ChevronRight,
  GitBranch,
  Loader2,
  Scissors,
  Unplug,
  Upload,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { getStateInfo } from '@/app/(app)/git/utils'
import {
  publishProjectChanges,
  pullRepository,
  type RepoStatus,
} from '@/lib/api'
import { DashboardContent } from './project-row/DashboardContent'
import { PublishResultBlock } from './project-row/PublishResultBlock'
import { RemoteStatusBadge } from './RemoteStatusBadge'

interface ProjectRowProps {
  repo: RepoStatus
  remoteCheckedAt?: Date | null
}

const PUBLISH_RESULT_AUTO_DISMISS_MS = 4000

export function ProjectRow({ repo, remoteCheckedAt }: ProjectRowProps) {
  const [expanded, setExpanded] = useState(false)
  const [publishResult, setPublishResult] = useState<Awaited<
    ReturnType<typeof publishProjectChanges>
  > | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon
  const queryClient = useQueryClient()
  const workspaceSummary = repo.workspace_summary
  const repoKey = repo.project_id ?? repo.name
  const dirtyWorkspaceCount =
    (workspaceSummary?.dirty_checkpoints ?? 0) +
    (workspaceSummary?.dirty_main_repo ? 1 : 0)
  const canPublish = repo.uncommitted > 0 || repo.ahead > 0

  const syncMutation = useMutation({
    mutationFn: () => pullRepository(repoKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['git-status'] })
      queryClient.invalidateQueries({
        queryKey: ['project-dashboard', repoKey],
      })
      queryClient.invalidateQueries({ queryKey: ['git-conflicts'] })
    },
  })

  const publishMutation = useMutation({
    mutationFn: () => publishProjectChanges(repoKey),
    onMutate: () => {
      setPublishResult(null)
    },
    onSuccess: (result) => {
      setPublishResult(result)
      queryClient.invalidateQueries({ queryKey: ['git-status'] })
      queryClient.invalidateQueries({
        queryKey: ['project-dashboard', repoKey],
      })
    },
    onError: () => {
      setPublishResult(null)
    },
  })

  useEffect(() => {
    if (!publishResult) return undefined
    const id = window.setTimeout(
      () => setPublishResult(null),
      PUBLISH_RESULT_AUTO_DISMISS_MS,
    )
    return () => window.clearTimeout(id)
  }, [publishResult])

  const wsBadges: Array<{
    icon: typeof GitBranch
    count: number
    label: string
    tone: string
  }> = []
  if (workspaceSummary) {
    if (workspaceSummary.active_checkpoints > 0)
      wsBadges.push({
        icon: GitBranch,
        count: workspaceSummary.active_checkpoints,
        label: 'cp',
        tone: 'text-phosphor-400',
      })
    if (dirtyWorkspaceCount > 0)
      wsBadges.push({
        icon: AlertTriangle,
        count: dirtyWorkspaceCount,
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
        'rounded-lg border overflow-hidden transition-all duration-200 relative',
        'bg-slate-900/40',
        expanded
          ? 'border-slate-700/80 shadow-lg shadow-black/30 shadow-outrun-500/[0.03]'
          : 'border-slate-800/60 hover:border-slate-700/60',
      )}
    >
      {/* State accent strip */}
      <div
        className={clsx(
          'absolute left-0 top-0 bottom-0 w-[2px] rounded-l-lg transition-colors duration-200',
          stateInfo.stripColor ?? 'bg-transparent',
        )}
        aria-hidden="true"
      />
      {/* Header — entire row is clickable for expand */}
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
        className="flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500/40"
      >
        {/* Chevron */}
        <ChevronRight
          className={clsx(
            'w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-all duration-200 shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* Repo name */}
        <span className="font-semibold text-slate-100 text-sm tracking-tight shrink-0">
          {repo.name}
        </span>

        {/* Branch */}
        <span className="text-2xs font-mono text-slate-500 truncate min-w-0">
          {repo.branch}
        </span>

        {/* Workspace badges — compact inline */}
        {wsBadges.map((b) => (
          <span
            key={b.label}
            className={clsx(
              'hidden md:flex items-center gap-0.5 text-[10px] font-mono shrink-0',
              b.tone,
            )}
            title={`${b.count} ${b.label}`}
          >
            <b.icon className="w-2.5 h-2.5" />
            {b.count}
          </span>
        ))}

        {/* Right side — status cluster */}
        <div className="flex items-center gap-2.5 ml-auto shrink-0">
          {/* State pill */}
          <span
            className={clsx(
              'flex items-center gap-1 text-2xs px-2 py-0.5 rounded-md',
              stateInfo.bg,
              stateInfo.color,
            )}
          >
            <StateIcon className="w-3 h-3" />
            {stateInfo.label}
            {repo.state === 'dirty' && repo.uncommitted > 0 && (
              <span className="opacity-70">({repo.uncommitted})</span>
            )}
          </span>

          {/* Ahead / behind */}
          <RemoteStatusBadge
            ahead={repo.ahead}
            behind={repo.behind}
            branch={repo.branch}
            checkedAt={remoteCheckedAt}
            compact
          />

          {/* Sync button — stops propagation so it doesn't toggle expand */}
          <button
            type="button"
            disabled={syncMutation.isPending}
            onClick={(e) => {
              e.stopPropagation()
              syncMutation.mutate()
            }}
            title="Pull latest remote changes with fast-forward only."
            className={clsx(
              'flex items-center gap-1 px-2.5 py-1 rounded-md text-2xs font-medium transition-all',
              syncMutation.isPending
                ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                : 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 hover:bg-cyan-500/15 hover:border-cyan-500/40',
            )}
          >
            {syncMutation.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <ArrowDown className="w-3 h-3" />
            )}
            {syncMutation.isPending ? 'Syncing' : 'Sync'}
          </button>

          {canPublish && (
            <button
              type="button"
              disabled={publishMutation.isPending}
              onClick={(e) => {
                e.stopPropagation()
                publishMutation.mutate()
              }}
              title="Run st commit for this project, then push published work."
              className={clsx(
                'flex items-center gap-1 px-2.5 py-1 rounded-md text-2xs font-medium transition-all',
                publishMutation.isPending
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-outrun-500/12 text-outrun-400 border border-outrun-500/20 hover:bg-outrun-500/20 hover:border-outrun-500/40',
              )}
            >
              {publishMutation.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Upload className="w-3 h-3" />
              )}
              {publishMutation.isPending ? 'Publishing' : 'Commit + Push'}
            </button>
          )}
        </div>
      </div>

      {/* Publish result */}
      {publishResult && (
        <div className="px-4 pb-2.5">
          <PublishResultBlock result={publishResult} />
        </div>
      )}

      {/* Expandable dashboard */}
      <div
        ref={contentRef}
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-4 py-3">
            {expanded ? <DashboardContent projectId={repoKey} /> : null}
          </div>
        </div>
      </div>
    </div>
  )
}
