'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Layers,
  Terminal,
} from 'lucide-react'
import { useState } from 'react'
import { getApiBase } from '@/lib/api/utils'

interface BranchInfo {
  name: string
  is_current: boolean
  has_worktree: boolean
  worktree_path?: string
  task_id?: string
  last_commit_short?: string
  last_commit_date?: string
}

interface BranchesResponse {
  branches: BranchInfo[]
  count: number
}

async function fetchBranches(): Promise<BranchesResponse> {
  const res = await fetch(`${getApiBase()}/api/git/branches`)
  if (!res.ok) {
    throw new Error('Failed to fetch branches')
  }
  return res.json()
}

function formatRelativeDate(dateStr: string | undefined): string {
  if (!dateStr) return ''

  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) {
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
    if (diffHours === 0) {
      const diffMins = Math.floor(diffMs / (1000 * 60))
      return diffMins <= 1 ? 'just now' : `${diffMins}m ago`
    }
    return `${diffHours}h ago`
  }
  if (diffDays === 1) return 'yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return `${Math.floor(diffDays / 30)}mo ago`
}

function BranchRow({ branch }: { branch: BranchInfo }) {
  const [showWorktreePath, setShowWorktreePath] = useState(false)

  // Shorten the home directory path for display
  const displayPath = branch.worktree_path?.replace(/^\/home\/[^/]+/, '~')

  return (
    <div
      className={clsx(
        'group relative px-4 py-3 border-b border-slate-700/30 last:border-b-0',
        'transition-colors duration-150',
        branch.is_current && 'bg-violet-500/5',
        branch.has_worktree && !branch.is_current && 'bg-phosphor-500/5',
        'hover:bg-slate-800/50',
      )}
    >
      <div className="flex items-center justify-between gap-4">
        {/* Left: Branch name and indicators */}
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {/* Branch icon */}
          <GitBranch
            className={clsx(
              'w-4 h-4 flex-shrink-0',
              branch.is_current ? 'text-violet-400' : 'text-slate-500',
            )}
          />

          {/* Branch name */}
          <span
            className={clsx(
              'mono text-sm truncate',
              branch.is_current
                ? 'text-violet-300 font-medium'
                : 'text-slate-300',
            )}
          >
            {branch.name}
          </span>

          {/* Current branch badge */}
          {branch.is_current && (
            <span className="flex-shrink-0 px-2 py-0.5 rounded text-2xs font-medium bg-violet-500/20 text-violet-400 border border-violet-500/30">
              current
            </span>
          )}

          {/* Worktree indicator */}
          {branch.has_worktree && (
            <button
              onClick={() => setShowWorktreePath(!showWorktreePath)}
              className={clsx(
                'flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-medium',
                'bg-phosphor-500/10 text-phosphor-500 border border-phosphor-500/30',
                'hover:bg-phosphor-500/20 transition-colors cursor-pointer',
              )}
              title={`Worktree: ${displayPath}`}
            >
              <Layers className="w-3 h-3" />
              worktree
            </button>
          )}
        </div>

        {/* Right: Commit info */}
        <div className="flex items-center gap-4 flex-shrink-0">
          {branch.last_commit_short && (
            <span className="mono text-xs text-slate-500">
              {branch.last_commit_short}
            </span>
          )}
          {branch.last_commit_date && (
            <span className="text-xs text-slate-600 min-w-[60px] text-right">
              {formatRelativeDate(branch.last_commit_date)}
            </span>
          )}
        </div>
      </div>

      {/* Worktree path tooltip (expanded) */}
      {showWorktreePath && branch.worktree_path && (
        <div
          className={clsx(
            'mt-2 p-2 rounded-md',
            'bg-slate-900/60 border border-phosphor-500/20',
          )}
        >
          <div className="flex items-center gap-2">
            <Terminal className="w-3 h-3 text-phosphor-500" />
            <code className="text-xs text-phosphor-400 mono">
              cd {displayPath}
            </code>
          </div>
        </div>
      )}
    </div>
  )
}

export function BranchList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['branches'],
    queryFn: fetchBranches,
    staleTime: 30000,
    refetchInterval: 60000,
  })

  const [isExpanded, setIsExpanded] = useState(true)

  // Auto-collapse if many branches
  const shouldDefaultCollapse = data && data.count > 10

  // Don't render section if no branches
  if (!isLoading && !isError && (!data || data.count === 0)) {
    return null
  }

  const worktreeCount = data?.branches.filter((b) => b.has_worktree).length ?? 0

  return (
    <section className="animate-in stagger-2">
      {/* Section Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between mb-4 group cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <div className="relative">
            <GitBranch className="w-6 h-6 text-violet-400" />
            {/* Glow effect */}
            <div className="absolute inset-0 blur-md bg-violet-500/30" />
          </div>
          <div className="text-left">
            <h2 className="font-semibold text-lg text-white">Branches</h2>
            <p className="text-xs text-slate-500">
              Local branches across repositories
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {data && (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-violet-500/10 border border-violet-500/20">
                <span className="text-violet-400 font-semibold">
                  {data.count}
                </span>
                <span className="text-slate-400 text-sm">branches</span>
              </div>
              {worktreeCount > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-phosphor-500/10 border border-phosphor-500/20">
                  <Layers className="w-3.5 h-3.5 text-phosphor-500" />
                  <span className="text-phosphor-500 font-semibold">
                    {worktreeCount}
                  </span>
                  <span className="text-slate-400 text-sm">with worktrees</span>
                </div>
              )}
            </div>
          )}
          {isExpanded ? (
            <ChevronDown className="w-5 h-5 text-slate-500 group-hover:text-slate-400 transition-colors" />
          ) : (
            <ChevronRight className="w-5 h-5 text-slate-500 group-hover:text-slate-400 transition-colors" />
          )}
        </div>
      </button>

      {/* Loading State */}
      {isLoading && (
        <div className="card p-6 text-center">
          <div className="inline-flex items-center gap-2 text-slate-400">
            <div className="w-4 h-4 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
            Loading branches...
          </div>
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="card p-5 border-rose-500/30">
          <div className="flex items-center gap-3 text-rose-400">
            <AlertCircle className="w-5 h-5" />
            <span className="text-sm">
              Failed to load branches. Git API may not be available.
            </span>
          </div>
        </div>
      )}

      {/* Branch List */}
      {data && data.count > 0 && isExpanded && (
        <div className="card-elevated rounded-lg overflow-hidden">
          {data.branches.map((branch) => (
            <BranchRow key={branch.name} branch={branch} />
          ))}
        </div>
      )}

      {/* Collapsed hint */}
      {data && data.count > 0 && !isExpanded && (
        <div className="card p-4 text-center text-sm text-slate-500">
          Click to expand {data.count} branches
        </div>
      )}
    </section>
  )
}
