'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Loader2,
  Sparkles,
} from 'lucide-react'
import { useState } from 'react'
import { smartSyncProject, type RepoStatus } from '@/lib/api'
import { getStateInfo } from '@/app/git/utils'
import { DashboardContent } from './project-row/DashboardContent'
import { SyncResultBlock } from './project-row/SyncResultBlock'

interface ProjectRowProps {
  repo: RepoStatus
  isConfigRepo?: boolean
}

export function ProjectRow({ repo, isConfigRepo = false }: ProjectRowProps) {
  const [expanded, setExpanded] = useState(false)
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon
  const queryClient = useQueryClient()

  const syncMutation = useMutation({
    mutationFn: () => smartSyncProject(repo.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['git-status'] })
      queryClient.invalidateQueries({ queryKey: ['project-dashboard', repo.name] })
    },
  })

  return (
    <div
      className={clsx(
        'rounded-xl border overflow-hidden transition-all duration-300',
        'bg-gradient-to-br from-slate-900 to-[#0f0a18]',
        'border-slate-800',
        expanded && !isConfigRepo && 'shadow-[0_0_30px_rgba(0,0,0,0.4)]',
      )}
    >
      <div className="flex items-center gap-3 px-5 py-3.5">
        {!isConfigRepo ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="shrink-0 text-slate-500 hover:text-white transition-colors"
          >
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        ) : (
          <div className="w-4 shrink-0" />
        )}

        <span className="font-semibold text-white tracking-tight text-[15px]">{repo.name}</span>

        <span className="text-xs font-mono text-cyan-400 px-2 py-0.5 rounded bg-cyan-500/8 border border-cyan-500/15 shrink-0">
          {repo.branch}
        </span>

        <span className={clsx('flex items-center gap-1 text-xs shrink-0', stateInfo.color)}>
          <StateIcon className="w-3 h-3" />
          {stateInfo.label}
        </span>

        {repo.state === 'dirty' && (
          <span className="w-2 h-2 rounded-full bg-pink-500 animate-pulse shadow-[0_0_8px_#ff0066] shrink-0" />
        )}

        <div className="flex items-center gap-3 text-[11px] font-mono text-slate-500 ml-auto shrink-0">
          <span className={clsx(repo.uncommitted > 0 && 'text-pink-400')}>
            {repo.uncommitted} change{repo.uncommitted !== 1 ? 's' : ''}
          </span>
          {repo.ahead > 0 && (
            <span className="text-cyan-400 flex items-center gap-0.5">
              <ArrowUp className="w-3 h-3" />{repo.ahead}
            </span>
          )}
          {repo.behind > 0 && (
            <span className="text-amber-400 flex items-center gap-0.5">
              <ArrowDown className="w-3 h-3" />{repo.behind}
            </span>
          )}
          {repo.ahead === 0 && repo.behind === 0 && (
            <span className="text-slate-600">in sync</span>
          )}
        </div>

        <button
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
      </div>

      {syncMutation.data && (
        <div className="px-5 pb-3">
          <SyncResultBlock result={syncMutation.data} />
        </div>
      )}

      {expanded && !isConfigRepo && (
        <div className="border-t border-slate-800/60 px-5 py-4">
          <DashboardContent projectId={repo.name} />
        </div>
      )}
    </div>
  )
}
