'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Archive,
  ChevronDown,
  Eye,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'
import Link from 'next/link'
import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { BackupExpandedRow } from '@/components/backup/BackupExpandedRow'
import { CollapsibleSection } from '@/components/backup/CollapsibleSection'
import { CreateBackupModal } from '@/components/backup/CreateBackupModal'
import { SetupChecklist } from '@/components/backup/SetupChecklist'
import { SourcesManager } from '@/components/backup/SourcesManager'
import { SourceTypeBadge } from '@/components/backup/SourceTypeBadge'
import { StatusBadge } from '@/components/backup/StatusBadge'
import { StatusRibbon } from '@/components/backup/StatusRibbon'
import { StorageCard } from '@/components/backup/StorageCard'
import { ScopeList } from '@/components/snapshots/ScopeList'
import { SnapshotSummaryCard } from '@/components/snapshots/SnapshotSummaryCard'
import {
  type Backup,
  type BackupSource,
  fetchAllBackups,
  fetchBackupHealth,
  fetchBackupSources,
  fetchStorageBackends,
  fetchStorageStatus,
  fetchStorageSummary,
} from '@/lib/api/backups'
import { fetchScopes, fetchSnapshotSummary } from '@/lib/api/snapshots'
import { formatBytes, formatDate, formatTimeAgo } from '@/lib/format'
import { POLL_NOTIFICATIONS, STALE_GIT } from '@/lib/polling'

type ViewMode = 'list' | 'grid'
const STORAGE_KEY = 'backups-view-mode'

function SectionHeading({
  title,
  summary,
  actions,
}: {
  title: string
  summary: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300 display">
          {title}
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">{summary}</p>
      </div>
      {actions}
    </div>
  )
}

// ─── Backup Grid Card ────────────────────────────────────────────

function BackupGridCard({
  backup,
  source,
}: {
  backup: Backup
  source: BackupSource | undefined
}) {
  const accentClass =
    backup.status === 'completed'
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
            backup.status === 'completed'
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
        <StatusBadge status={backup.status} />
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
      <div className="grid grid-cols-2 gap-1.5">
        <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Size
          </div>
          <div className="truncate text-xs text-slate-200 font-mono">
            {formatBytes(backup.size_bytes)}
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

// ─── Main ────────────────────────────────────────────────────────

export function BackupsClient() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [viewRaw, setViewRaw] = useState<ViewMode>('grid')
  const dispatchedAtRef = useRef(0)

  // Restore view preference
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'list' || stored === 'grid') setViewRaw(stored)
  }, [])

  const setView = useCallback((mode: ViewMode) => {
    setViewRaw(mode)
    localStorage.setItem(STORAGE_KEY, mode)
  }, [])

  // ─── Data ───────────────────────────────────────────────────────

  const { data: sources = [] } = useQuery({
    queryKey: ['backup-sources'],
    queryFn: () => fetchBackupSources(),
  })

  const sourceMap = useMemo(() => {
    const map: Record<string, BackupSource> = {}
    for (const s of sources) map[s.id] = s
    return map
  }, [sources])

  const {
    data: backupsData,
    isLoading: backupsLoading,
    error: backupsError,
    refetch: refetchBackups,
  } = useQuery({
    queryKey: ['all-backups', statusFilter],
    queryFn: () =>
      fetchAllBackups({ limit: 100, status: statusFilter || undefined }),
    refetchInterval: (query) => {
      const backups = query.state.data?.backups
      if (!backups) return 10000
      const hasActive = backups.some(
        (b: Backup) => b.status === 'pending' || b.status === 'running',
      )
      return hasActive || Date.now() - dispatchedAtRef.current < 30_000
        ? 3000
        : false
    },
  })

  const { data: storageSummary, isLoading: storageLoading } = useQuery({
    queryKey: ['storage-summary'],
    queryFn: () => fetchStorageSummary(),
  })

  const { data: storageStatus } = useQuery({
    queryKey: ['storage-status'],
    queryFn: fetchStorageStatus,
  })

  const { data: healthData, isLoading: healthLoading } = useQuery({
    queryKey: ['backup-health'],
    queryFn: fetchBackupHealth,
    refetchInterval: POLL_NOTIFICATIONS,
  })

  const { data: storageBackends = [] } = useQuery({
    queryKey: ['storage-backends'],
    queryFn: fetchStorageBackends,
  })

  const { data: snapshotSummary, isLoading: snapshotLoading } = useQuery({
    queryKey: ['snapshot-summary'],
    queryFn: () => fetchSnapshotSummary(),
    staleTime: STALE_GIT,
  })

  const { data: snapshotScopes = [] } = useQuery({
    queryKey: ['snapshot-scopes'],
    queryFn: () => fetchScopes(undefined, true),
    staleTime: STALE_GIT,
  })

  const backups = backupsData?.backups ?? []
  const activeSnapshotScopes = useMemo(
    () => snapshotScopes.filter((scope) => scope.scope_state === 'active'),
    [snapshotScopes],
  )
  const archivedSnapshotScopes = useMemo(
    () => snapshotScopes.filter((scope) => scope.scope_state === 'archived'),
    [snapshotScopes],
  )
  const healthySourceCount =
    healthData?.sources.filter((source) => source.health_status === 'green')
      .length ?? 0
  const failingSourceCount =
    healthData?.sources.filter((source) => source.health_status === 'red')
      .length ?? 0
  const enabledSourceCount = sources.filter((source) => source.enabled).length
  const overviewSummary =
    storageLoading || healthLoading
      ? 'Loading backup health, storage, and retention metrics.'
      : `${healthySourceCount} healthy, ${failingSourceCount} failing, ${storageSummary?.total_count ?? 0} backups, ${formatBytes(storageSummary?.total_bytes ?? 0)} stored`
  const sourcesSummary =
    sources.length === 0
      ? 'No sources configured yet.'
      : `${sources.length} sources, ${enabledSourceCount} scheduled${failingSourceCount > 0 ? `, ${failingSourceCount} failing` : ''}`
  const snapshotsSummary = `${activeSnapshotScopes.length} active scope${activeSnapshotScopes.length === 1 ? '' : 's'}, ${archivedSnapshotScopes.length} archived`
  const protectionSummary =
    'Current backup readiness, restore validation, and anything still blocking full protection.'

  // ─── Handlers ───────────────────────────────────────────────────

  const invalidateAll = async () => {
    dispatchedAtRef.current = Date.now()
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['all-backups'] }),
      queryClient.invalidateQueries({ queryKey: ['storage-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['backup-health'] }),
      queryClient.invalidateQueries({ queryKey: ['backup-sources'] }),
    ])
  }

  const refreshSources = () => {
    queryClient.invalidateQueries({ queryKey: ['backup-sources'] })
    queryClient.invalidateQueries({ queryKey: ['backup-health'] })
  }

  const refreshStorage = () => {
    queryClient.invalidateQueries({ queryKey: ['storage-backends'] })
    queryClient.invalidateQueries({ queryKey: ['storage-status'] })
  }

  const refreshSnapshots = () => {
    queryClient.invalidateQueries({ queryKey: ['snapshot-summary'] })
    queryClient.invalidateQueries({ queryKey: ['snapshot-scopes'] })
  }

  // ─── Render ─────────────────────────────────────────────────────

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {showCreateModal && (
        <CreateBackupModal
          sources={sources}
          onClose={() => setShowCreateModal(false)}
          onCreated={invalidateAll}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between hero-glow">
        <div className="flex items-center gap-3 relative z-10">
          <div className="p-1.5 rounded-md bg-indigo-500/10 border border-indigo-500/20">
            <Archive className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-100 display tracking-tight leading-none">
              Backup Operations
            </h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Sources, schedules, storage, and history
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {healthData && (
            <div className="hidden sm:flex items-center gap-3 text-sm mr-2">
              {healthData.sources.filter((s) => s.health_status === 'green')
                .length > 0 && (
                <span className="text-emerald-400">
                  {
                    healthData.sources.filter(
                      (s) => s.health_status === 'green',
                    ).length
                  }{' '}
                  healthy
                </span>
              )}
              {healthData.sources.filter((s) => s.health_status === 'red')
                .length > 0 && (
                <span className="text-red-400">
                  {
                    healthData.sources.filter((s) => s.health_status === 'red')
                      .length
                  }{' '}
                  failing
                </span>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 text-2xs px-3 py-1.5 rounded-md bg-phosphor-500/12 text-phosphor-400 border border-phosphor-500/20 hover:bg-phosphor-500/20 hover:border-phosphor-500/40 transition-all font-medium"
            data-testid="backup-manual-trigger"
          >
            <Plus className="w-3.5 h-3.5" />
            Create Backup
          </button>
        </div>
      </div>

      <section className="space-y-3">
        <SectionHeading title="Overview" summary={overviewSummary} />
        <div className="rounded-lg border border-slate-700/60 bg-slate-900/30 px-4 py-4">
          <StatusRibbon
            health={healthData}
            storageSummary={storageSummary}
            storageStatus={storageStatus}
            isLoading={storageLoading || healthLoading}
          />
        </div>
      </section>

      {/* Setup Checklist */}
      <section className="space-y-3">
        <SectionHeading title="Protection Status" summary={protectionSummary} />
        <SetupChecklist
          storageStatus={storageStatus}
          sources={sources}
          healthItems={healthData?.sources ?? []}
          isLoading={storageLoading || healthLoading}
          onSourceChanged={refreshSources}
          onBackupTriggered={invalidateAll}
        />
      </section>

      <CollapsibleSection title="Sources & Schedules" summary={sourcesSummary}>
        <SourcesManager
          sources={sources}
          healthItems={healthData?.sources ?? []}
          recentBackups={backups}
          onSourceChanged={refreshSources}
          onBackupTriggered={invalidateAll}
          showHeader={false}
        />
      </CollapsibleSection>

      {/* Storage */}
      <StorageCard
        backends={storageBackends}
        storageStatus={storageStatus}
        onRefresh={refreshStorage}
      />

      {/* Snapshots & Recovery */}
      <CollapsibleSection
        title="Snapshots & Recovery"
        summary={snapshotsSummary}
      >
        <div className="space-y-3">
          <SnapshotSummaryCard
            summary={snapshotSummary}
            isLoading={snapshotLoading}
            onMutated={refreshSnapshots}
          />
          <div className="space-y-2">
            <div>
              <div className="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                Active Protection Scopes
              </div>
              <ScopeList scopes={activeSnapshotScopes} />
            </div>
            {archivedSnapshotScopes.length > 0 && (
              <details className="rounded-lg border border-slate-700/60 bg-slate-800/30 overflow-hidden">
                <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      Archived Recovery Scopes
                    </div>
                    <div className="mt-0.5 text-xs text-slate-400">
                      Retained snapshots for deleted or retired lanes
                    </div>
                  </div>
                  <div className="text-xs font-medium text-amber-300">
                    {archivedSnapshotScopes.length}
                  </div>
                </summary>
                <div className="border-t border-slate-800/60 px-4 py-3">
                  <ScopeList scopes={archivedSnapshotScopes} />
                </div>
              </details>
            )}
          </div>
        </div>
      </CollapsibleSection>

      {/* Backup History */}
      <section className="space-y-3">
        <SectionHeading
          title="Backup History"
          summary="All backups across sources"
          actions={
            <div className="flex items-center gap-3">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
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
          }
        />

        {backupsLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="flex items-center gap-2.5 text-slate-500 text-sm">
              <RefreshCw className="w-5 h-5 animate-spin text-phosphor-500" />
              Loading backups...
            </div>
          </div>
        ) : backupsError ? (
          <div className="p-4 rounded-lg bg-rose-500/8 border border-rose-500/20 text-rose-300 flex items-center gap-3 text-sm">
            <AlertCircle className="w-5 h-5 text-rose-500 shrink-0" />
            <div>
              <span className="font-medium text-slate-100">
                Failed to load backups.
              </span>{' '}
              <button
                type="button"
                onClick={() => refetchBackups()}
                className="text-rose-300 hover:text-slate-100 underline"
              >
                Try again
              </button>
            </div>
          </div>
        ) : backups.length === 0 ? (
          <div className="text-center py-20 text-slate-600">
            <Archive className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm">
              {statusFilter
                ? `No backups with status "${statusFilter}"`
                : 'No backups yet'}
            </p>
          </div>
        ) : viewRaw === 'grid' ? (
          /* Grid view */
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {backups.map((backup) => (
              <BackupGridCard
                key={backup.id}
                backup={backup}
                source={sourceMap[backup.source_id]}
              />
            ))}
          </div>
        ) : (
          /* List view */
          <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/60 bg-slate-900/50">
                  <th className="px-4 py-2.5 text-left text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em] w-8" />
                  <th className="px-4 py-2.5 text-left text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em]">
                    Source
                  </th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em]">
                    Status
                  </th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em] hidden sm:table-cell">
                    Type
                  </th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em] hidden md:table-cell">
                    Size
                  </th>
                  <th className="px-4 py-2.5 text-left text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em] hidden lg:table-cell">
                    Created
                  </th>
                  <th className="px-4 py-2.5 text-right text-[10px] font-medium text-slate-500 uppercase tracking-[0.14em]">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {backups.map((backup) => {
                  const isExpanded = expandedId === backup.id
                  const source = sourceMap[backup.source_id]
                  return (
                    <Fragment key={backup.id}>
                      <tr
                        className={clsx(
                          'hover:bg-slate-800/30 transition-colors cursor-pointer',
                          isExpanded && 'bg-slate-800/20',
                        )}
                        onClick={() =>
                          setExpandedId(isExpanded ? null : backup.id)
                        }
                      >
                        <td className="px-4 py-2.5">
                          <ChevronDown
                            className={clsx(
                              'w-3.5 h-3.5 text-slate-600 transition-transform',
                              isExpanded && 'rotate-180',
                            )}
                          />
                        </td>
                        <td className="px-4 py-2.5">
                          <Link
                            href={`/backups/${backup.source_id}`}
                            className="text-sm text-phosphor-400 hover:text-phosphor-300 inline-flex items-center gap-2"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {source?.name ?? backup.source_id}
                            {source && (
                              <SourceTypeBadge type={source.source_type} />
                            )}
                          </Link>
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-1.5">
                            <StatusBadge status={backup.status} />
                            {backup.verified != null && (
                              <span
                                title={
                                  backup.verified
                                    ? 'Verified'
                                    : 'Verification failed'
                                }
                              >
                                {backup.verified ? (
                                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                                ) : (
                                  <ShieldX className="w-3.5 h-3.5 text-red-400" />
                                )}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-2.5 hidden sm:table-cell">
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
                        </td>
                        <td className="px-4 py-2.5 hidden md:table-cell">
                          <span className="text-xs text-slate-300 font-mono">
                            {formatBytes(backup.size_bytes)}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 hidden lg:table-cell">
                          <span className="text-xs text-slate-400">
                            {formatDate(backup.created_at)}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <div
                            className="flex items-center justify-end gap-1.5"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Link
                              href={`/backups/${backup.source_id}`}
                              className="p-1 text-slate-500 hover:text-phosphor-400 transition-colors"
                              title="View Source"
                            >
                              <Eye className="w-3.5 h-3.5" />
                            </Link>
                            {backup.status === 'completed' && (
                              <Link
                                href={`/backups/${backup.source_id}/restore/${backup.id}`}
                                className="p-1 text-slate-500 hover:text-amber-400 transition-colors"
                                title="Restore"
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                              </Link>
                            )}
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <BackupExpandedRow
                          backup={backup}
                          sourceName={source?.name ?? backup.source_id}
                          sourceType={source?.source_type}
                        />
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
