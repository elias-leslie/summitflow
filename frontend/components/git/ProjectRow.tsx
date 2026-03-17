'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Layers,
  Loader2,
  Scissors,
  Sparkles,
  Unplug,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { getStateInfo } from '@/app/git/utils'
import { type RepoStatus, smartSyncProject } from '@/lib/api'
import { DashboardContent } from './project-row/DashboardContent'
import { SyncResultBlock } from './project-row/SyncResultBlock'

interface ProjectRowProps {
  repo: RepoStatus
  isConfigRepo?: boolean
}

const SYNC_RESULT_AUTO_DISMISS_MS = 12000

function WorkspaceBadge({
  tone,
  icon: Icon,
  label,
  title,
}: {
  tone: 'cyan' | 'amber' | 'rose'
  icon: typeof Layers
  label: string
  title: string
}) {
  const tones = {
    cyan: 'bg-phosphor-500/10 text-phosphor-300 border-phosphor-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    rose: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  }

  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-mono uppercase tracking-wide',
        tones[tone],
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  )
}

export function ProjectRow({ repo, isConfigRepo = false }: ProjectRowProps) {
  const [expanded, setExpanded] = useState(false)
  const [syncResult, setSyncResult] = useState<Awaited<
    ReturnType<typeof smartSyncProject>
  > | null>(null)
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon
  const queryClient = useQueryClient()
  const workspaceSummary = repo.workspace_summary
  const repoKey = repo.project_id ?? repo.name
  const worktreePreview = workspaceSummary?.worktree_task_ids.length
    ? ` (${workspaceSummary.worktree_task_ids.join(', ')})`
    : ''

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

    const timeoutId = window.setTimeout(() => {
      setSyncResult(null)
    }, SYNC_RESULT_AUTO_DISMISS_MS)

    return () => window.clearTimeout(timeoutId)
  }, [syncResult])

  return (
    <div
      className={clsx(
        'rounded-xl border overflow-hidden transition-all duration-300',
        'bg-gradient-to-br from-slate-900 to-[#0f0a18]',
        'border-slate-800',
        expanded && !isConfigRepo && 'shadow-[0_0_30px_rgba(0,0,0,0.4)]',
      )}
    >
      <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
        {!isConfigRepo ? (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="shrink-0 text-slate-500 hover:text-white transition-colors"
          >
            {expanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
        ) : (
          <div className="w-4 shrink-0" />
        )}

        <span className="font-semibold text-white tracking-tight text-[15px]">
          {repo.name}
        </span>

        <span className="text-xs font-mono text-phosphor-400 px-2 py-0.5 rounded bg-phosphor-500/8 border border-phosphor-500/15 shrink-0">
          {repo.branch}
        </span>

        <span
          className={clsx(
            'flex items-center gap-1 text-xs shrink-0',
            stateInfo.color,
          )}
        >
          <StateIcon className="w-3 h-3" />
          {stateInfo.label}
        </span>

        {!isConfigRepo &&
          workspaceSummary &&
          workspaceSummary.active_worktrees > 0 && (
            <WorkspaceBadge
              tone="cyan"
              icon={Layers}
              label={`${workspaceSummary.active_worktrees} worktree${workspaceSummary.active_worktrees === 1 ? '' : 's'}`}
              title={`Active worktrees${worktreePreview}`}
            />
          )}

        {!isConfigRepo &&
          workspaceSummary &&
          workspaceSummary.dirty_worktrees > 0 && (
            <WorkspaceBadge
              tone="rose"
              icon={AlertTriangle}
              label={`${workspaceSummary.dirty_worktrees} dirty wt`}
              title={`${workspaceSummary.dirty_worktrees} worktree${workspaceSummary.dirty_worktrees === 1 ? '' : 's'} with uncommitted changes`}
            />
          )}

        {!isConfigRepo &&
          workspaceSummary &&
          workspaceSummary.orphan_branches > 0 && (
            <WorkspaceBadge
              tone="amber"
              icon={Unplug}
              label={`${workspaceSummary.orphan_branches} orphan`}
              title={`${workspaceSummary.orphan_branches} task branch${workspaceSummary.orphan_branches === 1 ? '' : 'es'} without a worktree`}
            />
          )}

        {!isConfigRepo &&
          workspaceSummary &&
          workspaceSummary.prunable_branches > 0 && (
            <WorkspaceBadge
              tone="rose"
              icon={Scissors}
              label={`${workspaceSummary.prunable_branches} prune`}
              title={`${workspaceSummary.prunable_branches} merged branch${workspaceSummary.prunable_branches === 1 ? '' : 'es'} can be cleaned up`}
            />
          )}

        {repo.state === 'dirty' && (
          <span className="w-2 h-2 rounded-full bg-pink-500 animate-pulse shadow-[0_0_8px_#ff0066] shrink-0" />
        )}

        <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500 md:ml-auto shrink-0">
          <span className={clsx(repo.uncommitted > 0 && 'text-pink-400')}>
            {repo.uncommitted} change{repo.uncommitted !== 1 ? 's' : ''}
          </span>
          {repo.ahead > 0 && (
            <span className="text-phosphor-400 flex items-center gap-0.5">
              <ArrowUp className="w-3 h-3" />
              {repo.ahead}
            </span>
          )}
          {repo.behind > 0 && (
            <span className="text-amber-400 flex items-center gap-0.5">
              <ArrowDown className="w-3 h-3" />
              {repo.behind}
            </span>
          )}
          {repo.ahead === 0 && repo.behind === 0 && (
            <span className="text-slate-600">in sync</span>
          )}
        </div>

        {!isConfigRepo && (
          <button
            type="button"
            disabled={syncMutation.isPending}
            onClick={(e) => {
              e.stopPropagation()
              syncMutation.mutate()
            }}
            className={clsx(
              'shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
              syncMutation.isPending
                ? 'bg-slate-800 text-slate-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-pink-600/80 to-purple-600/80 hover:from-pink-500 hover:to-purple-500 text-white shadow-lg shadow-pink-500/10 hover:shadow-pink-500/25',
            )}
          >
            {syncMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            {syncMutation.isPending ? 'Syncing...' : 'Smart Sync'}
          </button>
        )}
      </div>

      {syncResult && (
        <div className="px-5 pb-3">
          <SyncResultBlock result={syncResult} />
        </div>
      )}

      {expanded && !isConfigRepo && (
        <div className="border-t border-slate-800/60 px-5 py-4">
          <DashboardContent projectId={repoKey} />
        </div>
      )}
    </div>
  )
}
