'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  ChevronRight,
  Loader2,
  RotateCcw,
} from 'lucide-react'
import { useCallback, useState } from 'react'
import {
  type BtrfsScope,
  type BtrfsSnapshot,
  fetchSnapshots,
  recoverSnapshot,
} from '@/lib/api/snapshots'
import { formatBytes, formatTimeAgo } from '@/lib/format'

// ─── Source styling ─────────────────────────────────────────────

const SOURCE_DOT: Record<string, string> = {
  manual: 'bg-phosphor-500',
  'auto-baseline': 'bg-emerald-500',
  'auto-periodic': 'bg-slate-500',
  'auto-claim': 'bg-amber-500',
}

const SOURCE_BADGE: Record<string, string> = {
  manual: 'bg-phosphor-500/12 text-phosphor-400 border-phosphor-500/20',
  'auto-baseline': 'bg-emerald-500/12 text-emerald-400 border-emerald-500/20',
  'auto-periodic': 'bg-slate-700/50 text-slate-500 border-slate-600/40',
  'auto-claim': 'bg-amber-500/12 text-amber-400 border-amber-500/20',
}

const SOURCE_LABEL: Record<string, string> = {
  manual: 'manual',
  'auto-baseline': 'baseline',
  'auto-periodic': 'periodic',
  'auto-claim': 'claim',
}

const SCOPE_TYPE_STYLE: Record<string, string> = {
  project: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  lane: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
}

const SCOPE_ACCENT: Record<string, string> = {
  project: 'border-l-emerald-500',
  lane: 'border-l-blue-500',
}

// ─── Snapshot Row ───────────────────────────────────────────────

function SnapshotRow({ snap }: { snap: BtrfsSnapshot }) {
  const [recovering, setRecovering] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const handleRecover = useCallback(async () => {
    setRecovering(true)
    setResult(null)
    try {
      const res = await recoverSnapshot(snap.id, snap.project_id)
      setResult(res.ok ? 'Recovered' : res.error ?? 'Failed')
    } catch {
      setResult('Failed')
    }
    setRecovering(false)
    setTimeout(() => setResult(null), 3000)
  }, [snap.id, snap.project_id])

  const displayName = snap.name ?? snap.id.slice(0, 20)
  const dotClass = SOURCE_DOT[snap.source] ?? 'bg-slate-600'
  const badgeClass = SOURCE_BADGE[snap.source] ?? SOURCE_BADGE['auto-periodic']
  const label = SOURCE_LABEL[snap.source] ?? snap.source

  return (
    <div className="flex items-center gap-3 text-xs px-2.5 py-1.5 rounded bg-slate-950/40 border border-slate-800/40">
      <div className={clsx('w-1.5 h-1.5 rounded-full shrink-0', dotClass)} />
      <span
        className={clsx(
          'inline-flex items-center px-1.5 py-0.5 rounded text-[9px] uppercase tracking-[0.1em] font-medium border leading-none shrink-0',
          badgeClass,
        )}
      >
        {label}
      </span>
      <span className="text-slate-300 truncate min-w-0" title={snap.id}>
        {displayName}
      </span>
      {snap.branch && (
        <span className="hidden sm:inline text-slate-600 font-mono truncate max-w-[120px]">
          {snap.branch}
        </span>
      )}
      <span className="text-slate-600 shrink-0 ml-auto">
        {formatTimeAgo(snap.created_at)}
      </span>
      {snap.usage && (
        <span className="text-slate-600 font-mono shrink-0 hidden sm:inline">
          {formatBytes(snap.usage.exclusive_bytes)}
        </span>
      )}
      <button
        type="button"
        onClick={handleRecover}
        disabled={recovering}
        className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 disabled:opacity-40 transition-all shrink-0"
        title="Recover to sibling scope"
      >
        {recovering ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <RotateCcw className="w-3 h-3" />
        )}
      </button>
      {result && (
        <span
          className={clsx(
            'text-[9px] font-mono shrink-0',
            result === 'Recovered' ? 'text-emerald-400' : 'text-rose-400',
          )}
        >
          {result}
        </span>
      )}
    </div>
  )
}

// ─── Scope Card ─────────────────────────────────────────────────

function ScopeCard({ scope }: { scope: BtrfsScope }) {
  const [expanded, setExpanded] = useState(false)

  const { data: snapshots, isLoading } = useQuery({
    queryKey: ['snapshot-scope', scope.project_id, scope.scope_type, scope.scope_name],
    queryFn: () => fetchSnapshots(scope.project_id, scope.scope_type),
    enabled: expanded,
    staleTime: 30_000,
  })

  // Filter to this scope
  const scopeSnaps = snapshots?.filter(
    (s) => s.scope_name === scope.scope_name && s.scope_type === scope.scope_type,
  )

  const accentClass = SCOPE_ACCENT[scope.scope_type] ?? 'border-l-slate-600'
  const typeStyle = SCOPE_TYPE_STYLE[scope.scope_type] ?? 'bg-slate-600 text-slate-300 border-slate-500'

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
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => e.key === 'Enter' && setExpanded(!expanded)}
        className="flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none group"
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
        <span className="text-sm text-white font-medium truncate">
          {scope.scope_name}
        </span>
        <span className="text-[10px] text-slate-600 rounded bg-slate-900/60 px-1.5 py-0.5 shrink-0">
          {scope.snapshot_count}
        </span>
        <div className="hidden sm:flex items-center gap-3 text-2xs text-slate-500 ml-auto">
          {scope.total_bytes != null && scope.total_bytes > 0 && (
            <span className="font-mono">{formatBytes(scope.total_bytes)}</span>
          )}
          {scope.newest_at && (
            <span>{formatTimeAgo(scope.newest_at)}</span>
          )}
        </div>
      </div>

      {/* Expanded content */}
      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-4 py-3 space-y-1.5">
            {isLoading ? (
              <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
                <Loader2 className="w-3 h-3 animate-spin" />
                Loading snapshots...
              </div>
            ) : scopeSnaps && scopeSnaps.length > 0 ? (
              scopeSnaps.map((snap) => (
                <SnapshotRow key={snap.id} snap={snap} />
              ))
            ) : (
              <div className="text-xs text-slate-600 py-1">
                No snapshots in this scope
              </div>
            )}
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
      <div className="text-xs text-slate-600 py-2">
        No snapshot scopes found
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {scopes.map((scope) => (
        <ScopeCard
          key={`${scope.project_id}-${scope.scope_type}-${scope.scope_name}`}
          scope={scope}
        />
      ))}
    </div>
  )
}
