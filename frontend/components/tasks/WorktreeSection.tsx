'use client'

import clsx from 'clsx'
import { Copy, GitBranch, Layers } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { getErrorMessage } from '@/lib/utils'

interface WorktreeSectionProps {
  worktree: {
    path: string
    branch: string
    is_active: boolean
  }
}

export function WorktreeSection({ worktree }: WorktreeSectionProps) {
  const [copied, setCopied] = useState(false)

  // Shorten the home directory path for display
  const displayPath = worktree.path.replace(/^\/home\/[^/]+/, '~')

  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(worktree.path)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to copy worktree path'))
    }
  }

  return (
    <div
      className={clsx(
        'relative overflow-hidden',
        'p-4 rounded-lg',
        'bg-slate-800/50 border border-phosphor-500/20',
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="relative w-8 h-8 rounded-lg bg-phosphor-500/15 flex items-center justify-center">
            <Layers className="w-4 h-4 text-phosphor-500" />
            {/* Active pulse indicator */}
            {worktree.is_active && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-phosphor-500 shadow-[0_0_6px_rgba(0,245,255,0.7)]" />
            )}
          </div>
          <div>
            <h3 className="text-sm font-medium text-white">Active Worktree</h3>
            <span className="text-xs text-slate-500">Isolated workspace</span>
          </div>
        </div>

        {/* Active badge */}
        <div
          className={clsx(
            'flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
            worktree.is_active
              ? 'bg-phosphor-500/10 text-phosphor-500 border-phosphor-500/30'
              : 'bg-slate-500/10 text-slate-400 border-slate-500/30',
          )}
        >
          {worktree.is_active ? 'Active' : 'Inactive'}
        </div>
      </div>

      {/* Branch info */}
      <div className="flex items-center gap-2 mb-3">
        <GitBranch className="w-3.5 h-3.5 text-violet-400" />
        <span className="text-xs text-slate-500 uppercase tracking-wider">
          Branch:
        </span>
        <span className="text-sm text-violet-300 font-mono">{worktree.branch}</span>
      </div>

      {/* Path with copy button */}
      <div
        className={clsx(
          'flex items-center justify-between gap-2 p-2 rounded-md',
          'bg-slate-900/60 border border-slate-700/50',
        )}
      >
        <code className="text-xs text-phosphor-400 font-mono truncate flex-1">
          {displayPath}
        </code>
        <button
          type="button"
          onClick={handleCopyPath}
          className={clsx(
            'flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors',
            'hover:bg-slate-700/50',
            copied
              ? 'text-green-400'
              : 'text-slate-400 hover:text-phosphor-400',
          )}
          title="Copy full path"
        >
          <Copy className="w-3 h-3" />
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
    </div>
  )
}
