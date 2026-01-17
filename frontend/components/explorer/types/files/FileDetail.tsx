/**
 * FileDetail - Detail panel for files
 *
 * Shows extended file information: git history, bloat status, etc.
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'

interface FileDetailProps {
  entry: ExplorerEntry
}

// Helpers
const formatNumber = (n: number | undefined | null) => (n ?? 0).toLocaleString()

const formatBytes = (bytes: number | undefined | null) => {
  const b = bytes ?? 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

export function FileDetail({ entry }: FileDetailProps) {
  const meta = entry.metadata
  const isDir = meta.is_directory

  return (
    <div className="space-y-4">
      {/* Path */}
      <div>
        <span className="text-xs text-slate-500 uppercase tracking-wide">
          Path
        </span>
        <p className="font-mono text-sm text-slate-300 mt-1 break-all">
          {entry.path}
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {/* Size */}
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Size
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {formatBytes(meta.size_bytes)}
          </p>
        </div>

        {/* Lines of code */}
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Lines
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {formatNumber(meta.lines_of_code)}
          </p>
        </div>

        {/* File count (directories only) */}
        {isDir && (
          <div>
            <span className="text-xs text-slate-500 uppercase tracking-wide">
              Files
            </span>
            <p className="font-mono text-sm text-slate-200 mt-1">
              {formatNumber(meta.file_count)}
            </p>
          </div>
        )}

        {/* Extension (files only) */}
        {!isDir && meta.extension && (
          <div>
            <span className="text-xs text-slate-500 uppercase tracking-wide">
              Type
            </span>
            <p className="font-mono text-sm text-slate-200 mt-1">
              {meta.extension}
            </p>
          </div>
        )}
      </div>

      {/* Status badges */}
      <div className="flex flex-wrap gap-2">
        {/* Bloat level */}
        {meta.bloat_level && (
          <span
            className={cn(
              'px-2 py-0.5 rounded text-xs font-medium',
              meta.bloat_level === 'critical' && 'bg-red-500/20 text-red-400',
              meta.bloat_level === 'warning' &&
                'bg-amber-500/20 text-amber-400',
            )}
          >
            {meta.bloat_level === 'critical'
              ? 'Bloat: Critical'
              : 'Bloat: Warning'}
          </span>
        )}

        {/* Stale status */}
        {meta.stale_status && meta.stale_status !== 'fresh' && (
          <span
            className={cn(
              'px-2 py-0.5 rounded text-xs font-medium',
              meta.stale_status === 'orphan' &&
                'bg-purple-500/20 text-purple-400',
              meta.stale_status === 'stale' && 'bg-slate-500/20 text-slate-400',
              meta.stale_status === 'untracked' &&
                'bg-blue-500/20 text-blue-400',
            )}
          >
            {meta.stale_status.charAt(0).toUpperCase() +
              meta.stale_status.slice(1)}
          </span>
        )}
      </div>

      {/* Last commit info */}
      {meta.last_commit_hash && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Last Commit
          </span>
          <div className="mt-1 flex items-start gap-2">
            <code className="text-xs font-mono text-phosphor-400">
              {meta.last_commit_hash.slice(0, 7)}
            </code>
            <span className="text-sm text-slate-400 line-clamp-2">
              {meta.last_commit_message}
            </span>
          </div>
          {meta.last_commit_days !== undefined && (
            <p className="text-xs text-slate-500 mt-1">
              {meta.last_commit_days === 0
                ? 'Today'
                : meta.last_commit_days === 1
                  ? 'Yesterday'
                  : `${meta.last_commit_days} days ago`}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
