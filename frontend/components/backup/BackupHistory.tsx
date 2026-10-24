'use client'

import { clsx } from 'clsx'
import { Archive, Eye, RotateCcw, ShieldCheck, ShieldX } from 'lucide-react'
import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Backup, BackupSource } from '@/lib/api/backups'
import { formatDate, formatTimeAgo } from '@/lib/format'
import {
  type BackupColumn,
  BackupHistoryTable,
  BackupTypeBadge,
} from './BackupHistoryTable'
import { BackupSizeDetails, BackupSizeExplanation } from './BackupSizeDetails'
import { SourceTypeBadge } from './SourceTypeBadge'
import { backupDisplayStatus, StatusBadge } from './StatusBadge'

type ViewMode = 'list' | 'grid'
const STORAGE_KEY = 'backups-view-mode'

// ─── Backup Grid Card ────────────────────────────────────────────

function BackupGridCard({
  backup,
  source,
}: {
  backup: Backup
  source: BackupSource | undefined
}) {
  const displayStatus = backupDisplayStatus(
    backup.status,
    backup.verification_json?.activity,
  )
  const accentClass =
    displayStatus === 'cancelled'
      ? 'border-l-slate-500'
      : backup.status === 'completed'
        ? 'border-l-emerald-500'
        : backup.status === 'failed'
          ? 'border-l-red-500'
          : backup.status === 'running'
            ? 'border-l-blue-500'
            : 'border-l-amber-500'

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 p-4 transition-colors hover:bg-slate-800/60',
        accentClass,
      )}
    >
      {/* Identity */}
      <div className="mb-2.5 flex items-center gap-2">
        <div
          className={clsx(
            'w-2 h-2 rounded-full shrink-0',
            displayStatus === 'cancelled'
              ? 'bg-slate-500'
              : backup.status === 'completed'
                ? 'bg-emerald-500'
                : backup.status === 'failed'
                  ? 'bg-red-500'
                  : backup.status === 'running'
                    ? 'bg-blue-500'
                    : 'bg-amber-500',
          )}
        />
        <span className="font-medium text-slate-100 text-sm truncate flex-1">
          {source?.name ?? backup.source_id}
        </span>
        {backup.verified != null && (
          <span title={backup.verified ? 'Verified' : 'Verification failed'}>
            {backup.verified ? (
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ShieldX className="w-3.5 h-3.5 text-red-400" />
            )}
          </span>
        )}
      </div>

      {/* Tags */}
      <div className="mb-2.5 flex flex-wrap gap-1.5">
        <StatusBadge
          status={backup.status}
          activity={backup.verification_json?.activity}
        />
        {source && <SourceTypeBadge type={source.source_type} />}
        <span
          className={clsx(
            'rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] border',
            backup.backup_type === 'scheduled'
              ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20'
              : 'bg-slate-700/70 text-slate-400 border-slate-600/40',
          )}
        >
          {backup.backup_type}
        </span>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-1.5">
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Size details
          </div>
          <div className="text-xs text-slate-200">
            <BackupSizeDetails backup={backup} />
          </div>
        </div>
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Created
          </div>
          <div className="truncate text-xs text-slate-200">
            {formatTimeAgo(backup.created_at)}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-3 flex items-center gap-2">
        <Link
          href={`/backups/${backup.source_id}`}
          className="text-2xs px-2 py-1 rounded bg-slate-700/50 text-slate-400 hover:bg-slate-700/80 transition-colors flex items-center gap-1"
        >
          <Eye className="w-3 h-3" />
          View
        </Link>
        {backup.status === 'completed' && (
          <Link
            href={`/backups/${backup.source_id}/restore/${backup.id}`}
            className="text-2xs px-2 py-1 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors flex items-center gap-1"
          >
            <RotateCcw className="w-3 h-3" />
            Restore
          </Link>
        )}
      </div>
    </div>
  )
}

// ─── View Toggle ─────────────────────────────────────────────────

function ViewToggle({
  view,
  onViewChange,
}: {
  view: ViewMode
  onViewChange: (mode: ViewMode) => void
}) {
  return (
    <div className="flex rounded-md border border-slate-700/60 overflow-hidden">
      <button
        type="button"
        aria-pressed={view === 'grid'}
        onClick={() => onViewChange('grid')}
        className={clsx(
          'px-2.5 py-1 text-xs transition-colors',
          view === 'grid'
            ? 'bg-slate-700 text-slate-100'
            : 'bg-slate-900/50 text-slate-500 hover:text-slate-300',
        )}
        aria-label="Grid view"
      >
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 16 16"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <rect x="1" y="1" width="6" height="6" rx="1" />
          <rect x="9" y="1" width="6" height="6" rx="1" />
          <rect x="1" y="9" width="6" height="6" rx="1" />
          <rect x="9" y="9" width="6" height="6" rx="1" />
        </svg>
      </button>
      <button
        type="button"
        aria-pressed={view === 'list'}
        onClick={() => onViewChange('list')}
        className={clsx(
          'px-2.5 py-1 text-xs transition-colors',
          view === 'list'
            ? 'bg-slate-700 text-slate-100'
            : 'bg-slate-900/50 text-slate-500 hover:text-slate-300',
        )}
        aria-label="List view"
      >
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 16 16"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <line x1="1" y1="3" x2="15" y2="3" />
          <line x1="1" y1="8" x2="15" y2="8" />
          <line x1="1" y1="13" x2="15" y2="13" />
        </svg>
      </button>
    </div>
  )
}

// ─── History ─────────────────────────────────────────────────────

interface BackupHistoryProps {
  backups: Backup[]
  sources: BackupSource[]
  isLoading: boolean
  error: Error | null
  onRetry: () => void
  statusFilter: string
  onStatusFilterChange: (status: string) => void
}

/** Recent restic and archive backups across all sources. */
export function BackupHistory({
  backups,
  sources,
  isLoading: backupsLoading,
  error: backupsError,
  onRetry,
  statusFilter,
  onStatusFilterChange,
}: BackupHistoryProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [viewRaw, setViewRaw] = useState<ViewMode>('list')

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored === 'list' || stored === 'grid') setViewRaw(stored)
    } catch {
      // Storage can be unavailable; keep the default view.
    }
  }, [])

  const setView = useCallback((mode: ViewMode) => {
    setViewRaw(mode)
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      // Not remembered this time.
    }
  }, [])

  const sourceMap = useMemo(() => {
    const map: Record<string, BackupSource> = {}
    for (const s of sources) map[s.id] = s
    return map
  }, [sources])

  const columns = useMemo<BackupColumn[]>(
    () => [
      {
        key: 'source',
        label: 'Source',
        render: (backup) => {
          const source = sourceMap[backup.source_id]
          return (
            <Link
              href={`/backups/${backup.source_id}`}
              className="text-sm text-phosphor-400 hover:text-phosphor-300 inline-flex flex-wrap items-center gap-x-2 gap-y-1"
              onClick={(e) => e.stopPropagation()}
            >
              {source?.name ?? backup.source_id}
              {source && <SourceTypeBadge type={source.source_type} />}
            </Link>
          )
        },
      },
      {
        key: 'type',
        label: 'Type',
        className: 'hidden sm:table-cell',
        render: (backup) => <BackupTypeBadge backupType={backup.backup_type} />,
      },
      {
        key: 'size',
        label: 'Size details',
        className: 'hidden md:table-cell',
        render: (backup) => (
          <div className="text-xs text-slate-300 font-mono">
            <BackupSizeDetails backup={backup} />
          </div>
        ),
      },
      {
        key: 'created',
        label: 'Created',
        className: 'hidden lg:table-cell',
        render: (backup) => (
          <span className="text-xs text-slate-400">
            {formatDate(backup.created_at)}
          </span>
        ),
      },
    ],
    [sourceMap],
  )

  return (
    <section className="space-y-3" aria-labelledby="backup-history-heading">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2
            id="backup-history-heading"
            className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300 display"
          >
            History
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Most recent backups across all sources
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => onStatusFilterChange(e.target.value)}
            className="px-2 py-1 bg-slate-900/60 border border-slate-700/60 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-phosphor-500"
          >
            <option value="">All</option>
            <option value="completed">Completed</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
            <option value="failed">Failed</option>
          </select>
          <ViewToggle view={viewRaw} onViewChange={setView} />
        </div>
      </div>

      {viewRaw === 'grid' &&
      !backupsLoading &&
      !backupsError &&
      backups.length > 0 ? (
        <>
          <BackupSizeExplanation />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {backups.map((backup) => (
              <BackupGridCard
                key={backup.id}
                backup={backup}
                source={sourceMap[backup.source_id]}
              />
            ))}
          </div>
        </>
      ) : (
        <BackupHistoryTable
          backups={backups}
          isLoading={backupsLoading}
          hasError={Boolean(backupsError)}
          onRetry={onRetry}
          emptyState={
            <div className="text-center py-20 text-slate-600">
              <Archive className="w-8 h-8 mx-auto mb-3 opacity-40" />
              <p className="text-sm">
                {statusFilter
                  ? `No backups with status "${statusFilter}"`
                  : 'No backups yet'}
              </p>
            </div>
          }
          expandedId={expandedId}
          onToggleExpanded={setExpandedId}
          columns={columns}
          renderActions={(backup) => (
            <>
              <Link
                href={`/backups/${backup.source_id}`}
                className="p-1 text-slate-500 hover:text-phosphor-400 transition-colors"
                title="View source"
                aria-label="View source"
              >
                <Eye className="w-3.5 h-3.5" />
              </Link>
              {backup.status === 'completed' && (
                <Link
                  href={`/backups/${backup.source_id}/restore/${backup.id}`}
                  className="p-1 text-slate-500 hover:text-amber-400 transition-colors"
                  title="Restore"
                  aria-label="Restore"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                </Link>
              )}
            </>
          )}
          getExpandedSourceName={(backup) =>
            sourceMap[backup.source_id]?.name ?? backup.source_id
          }
          getExpandedSourceType={(backup) =>
            sourceMap[backup.source_id]?.source_type
          }
        />
      )}
    </section>
  )
}
