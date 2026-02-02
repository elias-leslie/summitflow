'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  Box,
  FolderGit2,
  GitBranch,
  Layers,
  Terminal,
} from 'lucide-react'
import { getApiBase } from '@/lib/api/utils'

interface WorktreeInfo {
  task_id: string
  path: string
  branch: string
  base_branch: string
  is_active: boolean
}

interface WorktreesResponse {
  worktrees: WorktreeInfo[]
  count: number
}

async function fetchWorktrees(): Promise<WorktreesResponse> {
  const res = await fetch(`${getApiBase()}/api/git/worktrees`)
  if (!res.ok) {
    throw new Error('Failed to fetch worktrees')
  }
  return res.json()
}

function WorktreeCard({ worktree }: { worktree: WorktreeInfo }) {
  // Shorten the home directory path for display
  const displayPath = worktree.path.replace(/^\/home\/[^/]+/, '~')

  return (
    <div
      className={clsx(
        'group relative overflow-hidden',
        'card-elevated p-5 rounded-lg transition-all duration-300',
        'hover:border-phosphor-500/50',
        'hover:shadow-[0_0_25px_rgba(0,245,255,0.12),0_0_50px_rgba(0,245,255,0.06)]',
      )}
    >
      {/* Isolation indicator - diagonal stripe pattern in corner */}
      <div
        className="absolute -top-6 -right-6 w-16 h-16 opacity-30"
        style={{
          background: `repeating-linear-gradient(
            -45deg,
            transparent,
            transparent 3px,
            rgba(0, 245, 255, 0.3) 3px,
            rgba(0, 245, 255, 0.3) 6px
          )`,
        }}
      />

      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="relative w-10 h-10 rounded-lg bg-phosphor-500/15 flex items-center justify-center">
            <Layers className="w-5 h-5 text-phosphor-500" />
            {/* Active pulse indicator */}
            {worktree.is_active && (
              <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-phosphor-500 shadow-[0_0_8px_rgba(0,245,255,0.7)]" />
            )}
          </div>
          <div>
            <h3 className="font-semibold text-white flex items-center gap-2">
              {worktree.task_id}
            </h3>
            <div className="flex items-center gap-1.5 text-xs text-slate-500">
              <FolderGit2 className="w-3 h-3" />
              <span>Isolated worktree</span>
            </div>
          </div>
        </div>

        {/* Active badge */}
        <div
          className={clsx(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
            worktree.is_active
              ? 'bg-phosphor-500/10 text-phosphor-500 border-phosphor-500/30'
              : 'bg-slate-500/10 text-slate-400 border-slate-500/30',
          )}
        >
          <Box className="w-3 h-3" />
          {worktree.is_active ? 'Active' : 'Inactive'}
        </div>
      </div>

      {/* Branch info */}
      <div className="space-y-2 mb-4">
        <div className="flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-violet-400" />
          <span className="text-xs text-slate-500 uppercase tracking-wider">
            Branch:
          </span>
          <span className="text-sm text-violet-300 mono">{worktree.branch}</span>
        </div>
        <div className="flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs text-slate-500 uppercase tracking-wider">
            Base:
          </span>
          <span className="text-sm text-slate-400 mono">
            {worktree.base_branch}
          </span>
        </div>
      </div>

      {/* Path display with copy-to-terminal hint */}
      <div
        className={clsx(
          'relative p-3 rounded-md',
          'bg-slate-900/60 border border-slate-700/50',
          'group-hover:border-phosphor-500/20 transition-colors',
        )}
      >
        <div className="flex items-center gap-2 mb-1">
          <Terminal className="w-3 h-3 text-slate-500" />
          <span className="text-2xs text-slate-500 uppercase tracking-wider">
            Worktree Path
          </span>
        </div>
        <code className="text-xs text-phosphor-400 mono block truncate">
          {displayPath}
        </code>
        {/* Hover hint */}
        <div
          className={clsx(
            'absolute inset-0 flex items-center justify-center',
            'bg-slate-900/90 rounded-md opacity-0',
            'group-hover:opacity-100 transition-opacity',
          )}
        >
          <span className="text-xs text-phosphor-400 flex items-center gap-1.5">
            <Terminal className="w-3.5 h-3.5" />
            cd {displayPath}
          </span>
        </div>
      </div>
    </div>
  )
}

export function WorktreeList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['worktrees'],
    queryFn: fetchWorktrees,
    staleTime: 30000,
    refetchInterval: 60000,
  })

  // Don't render section if no worktrees
  if (!isLoading && !isError && (!data || data.count === 0)) {
    return null
  }

  return (
    <section className="animate-in stagger-1">
      {/* Section Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="relative">
            <Layers className="w-6 h-6 text-phosphor-500" />
            {/* Glow effect */}
            <div className="absolute inset-0 blur-md bg-phosphor-500/30" />
          </div>
          <div>
            <h2 className="font-semibold text-lg text-white">
              Active Worktrees
            </h2>
            <p className="text-xs text-slate-500">
              Isolated workspaces for task development
            </p>
          </div>
        </div>
        {data && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-phosphor-500/10 border border-phosphor-500/20">
            <span className="text-phosphor-500 font-semibold">{data.count}</span>
            <span className="text-slate-400 text-sm">active</span>
          </div>
        )}
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="card p-6 text-center">
          <div className="inline-flex items-center gap-2 text-slate-400">
            <div className="w-4 h-4 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
            Loading worktrees...
          </div>
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="card p-5 border-rose-500/30">
          <div className="flex items-center gap-3 text-rose-400">
            <AlertCircle className="w-5 h-5" />
            <span className="text-sm">
              Failed to load worktrees. Worktree API may not be available.
            </span>
          </div>
        </div>
      )}

      {/* Worktree Grid */}
      {data && data.count > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.worktrees.map((worktree) => (
            <WorktreeCard key={worktree.task_id} worktree={worktree} />
          ))}
        </div>
      )}
    </section>
  )
}
