'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { ChevronRight, Loader2 } from 'lucide-react'
import { useId, useState } from 'react'
import { type BtrfsScope, fetchSnapshots } from '@/lib/api/snapshots'
import { formatBytes, formatTimeAgo } from '@/lib/format'
import { STALE_GIT } from '@/lib/polling'
import { SnapshotRow } from './SnapshotRow'

const SCOPE_TYPE_STYLE: Record<string, string> = {
  project: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
}

const SCOPE_ACCENT: Record<string, string> = {
  project: 'border-l-emerald-500',
}

const STATE_BADGE: Record<string, string> = {
  active: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/20',
  archived: 'bg-amber-500/12 text-amber-300 border-amber-500/20',
}

// ─── Scope Card ─────────────────────────────────────────────────

function ScopeCard({ scope }: { scope: BtrfsScope }) {
  const [expanded, setExpanded] = useState(false)
  const contentId = useId()

  const {
    data: snapshots,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: [
      'snapshot-scope',
      scope.project_id,
      scope.scope_type,
      scope.scope_name,
      scope.scope_state,
    ],
    queryFn: () =>
      fetchSnapshots(
        scope.project_id,
        scope.scope_type,
        scope.scope_name,
        scope.scope_state === 'archived',
      ),
    enabled: expanded,
    staleTime: STALE_GIT,
  })

  const accentClass = SCOPE_ACCENT[scope.scope_type] ?? 'border-l-slate-600'
  const typeStyle =
    SCOPE_TYPE_STYLE[scope.scope_type] ??
    'bg-slate-600 text-slate-300 border-slate-500'
  const stateStyle =
    STATE_BADGE[scope.scope_state] ??
    'bg-slate-700/50 text-slate-400 border-slate-600/40'

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 overflow-hidden transition-all duration-200',
        accentClass,
        expanded
          ? 'border-slate-700/80 shadow-lg shadow-black/20'
          : 'hover:bg-slate-800/60',
      )}
    >
      {/* Header */}
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left cursor-pointer select-none group focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
      >
        <ChevronRight
          className={clsx(
            'w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-all duration-200 shrink-0',
            expanded && 'rotate-90',
          )}
        />
        <span
          className={clsx(
            'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-[0.12em] font-medium border leading-none shrink-0',
            typeStyle,
          )}
        >
          {scope.scope_type}
        </span>
        <span
          className={clsx(
            'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-[0.12em] font-medium border leading-none shrink-0',
            stateStyle,
          )}
        >
          {scope.scope_state}
        </span>
        <span className="text-sm text-slate-100 font-medium truncate">
          {scope.scope_name}
        </span>
        <span className="text-[10px] text-slate-600 rounded bg-slate-900/60 px-1.5 py-0.5 shrink-0">
          {scope.snapshot_count}
        </span>
        <span className="hidden sm:flex items-center gap-3 text-2xs text-slate-400 ml-auto">
          <span className="font-mono">
            {scope.total_bytes == null
              ? 'Size unavailable'
              : scope.total_bytes === 0
                ? '0 B'
                : formatBytes(scope.total_bytes)}
          </span>
          {scope.newest_at && <span>{formatTimeAgo(scope.newest_at)}</span>}
        </span>
      </button>

      {/* Expanded content */}
      <div id={contentId} hidden={!expanded}>
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-4 py-3 space-y-1.5">
            {error && (
              <div className="space-y-2 py-1">
                <p role="alert" className="text-xs text-rose-300">
                  {snapshots
                    ? 'Refresh failed; showing last loaded snapshots: '
                    : 'Snapshots unavailable: '}
                  {error.message}
                </p>
                <button
                  type="button"
                  onClick={() => void refetch()}
                  className="btn-secondary text-xs"
                >
                  Retry snapshots
                </button>
              </div>
            )}
            {isLoading ? (
              <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
                <Loader2 className="w-3 h-3 animate-spin" />
                Loading snapshots...
              </div>
            ) : snapshots && snapshots.length > 0 ? (
              snapshots.map((snap) => <SnapshotRow key={snap.id} snap={snap} />)
            ) : !error ? (
              <div className="text-xs text-slate-400 py-1">
                No snapshots in this scope
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────────

interface ScopeListProps {
  scopes: BtrfsScope[]
}

export function ScopeList({ scopes }: ScopeListProps) {
  if (scopes.length === 0) {
    return (
      <div className="text-xs text-slate-400 py-2">
        No snapshot scopes found
      </div>
    )
  }

  const sortedScopes = [...scopes].sort((left, right) => {
    const leftNewest = left.newest_at ?? ''
    const rightNewest = right.newest_at ?? ''
    if (leftNewest !== rightNewest) {
      return rightNewest.localeCompare(leftNewest)
    }
    return left.scope_name.localeCompare(right.scope_name)
  })

  return (
    <div className="space-y-2">
      {sortedScopes.map((scope) => (
        <ScopeCard
          key={`${scope.project_id}-${scope.scope_type}-${scope.scope_name}-${scope.scope_state}`}
          scope={scope}
        />
      ))}
    </div>
  )
}
