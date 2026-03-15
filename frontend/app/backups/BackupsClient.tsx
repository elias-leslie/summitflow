'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Archive,
  ChevronDown,
  Eye,
  Loader2,
  Plus,
  RotateCcw,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'
import Link from 'next/link'
import { Fragment, useMemo, useRef, useState } from 'react'
import { BackupExpandedRow } from '@/components/backup/BackupExpandedRow'
import { CreateBackupModal } from '@/components/backup/CreateBackupModal'
import { SetupChecklist } from '@/components/backup/SetupChecklist'
import { SourceTypeBadge } from '@/components/backup/SourceTypeBadge'
import { SourcesManager } from '@/components/backup/SourcesManager'
import { StatusBadge } from '@/components/backup/StatusBadge'
import { StatusRibbon } from '@/components/backup/StatusRibbon'
import { StorageCard } from '@/components/backup/StorageCard'
import { WalCard } from '@/components/backup/WalCard'
import {
  type Backup,
  type BackupSource,
  fetchAllBackups,
  fetchBackupHealth,
  fetchBackupSources,
  fetchStorageBackends,
  fetchStorageSummary,
  fetchStorageStatus,
  fetchWalStatus,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

export function BackupsClient() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const dispatchedAtRef = useRef(0)

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
    refetchInterval: 30_000,
  })

  const { data: storageBackends = [] } = useQuery({
    queryKey: ['storage-backends'],
    queryFn: fetchStorageBackends,
  })

  const { data: walStatus, isLoading: walLoading } = useQuery({
    queryKey: ['wal-status'],
    queryFn: fetchWalStatus,
  })

  const backups = backupsData?.backups ?? []

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

  const refreshWal = () => {
    queryClient.invalidateQueries({ queryKey: ['wal-status'] })
  }

  // ─── Render ─────────────────────────────────────────────────────

  return (
    <main className="content-container py-8">
      {showCreateModal && (
        <CreateBackupModal
          sources={sources}
          onClose={() => setShowCreateModal(false)}
          onCreated={invalidateAll}
        />
      )}

      {/* Header */}
      <header className="mb-6 flex items-start justify-between">
        <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-3">
          <ShieldCheck className="w-6 h-6 text-slate-400" />
          Backup Operations
        </h1>
        <button
          type="button"
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-phosphor-600 text-white rounded-md
                     text-sm font-medium hover:bg-phosphor-500 transition-colors"
          data-testid="backup-manual-trigger"
        >
          <Plus className="w-4 h-4" />
          Create Backup
        </button>
      </header>

      {/* Setup Checklist — shows when backup protection has gaps */}
      <SetupChecklist
        storageStatus={storageStatus}
        sources={sources}
        healthItems={healthData?.sources ?? []}
        walStatus={walStatus}
        isLoading={storageLoading || healthLoading || walLoading}
        onSourceChanged={refreshSources}
        onBackupTriggered={invalidateAll}
        onWalRefresh={refreshWal}
      />

      {/* Status Ribbon */}
      <StatusRibbon
        health={healthData}
        storageSummary={storageSummary}
        storageStatus={storageStatus}
        isLoading={storageLoading || healthLoading}
      />

      {/* Sources & Schedules — unified management */}
      <SourcesManager
        sources={sources}
        healthItems={healthData?.sources ?? []}
        recentBackups={backups}
        onSourceChanged={refreshSources}
        onBackupTriggered={invalidateAll}
      />

      {/* Protection & Storage — side-by-side cards */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <WalCard
          walStatus={walStatus}
          isLoading={walLoading}
          onRefresh={refreshWal}
        />
        <StorageCard
          backends={storageBackends}
          storageStatus={storageStatus}
          onRefresh={refreshStorage}
        />
      </section>

      {/* Backup History */}
      <section>
        <div className="flex items-center gap-4 mb-4">
          <h2 className="text-sm font-medium text-slate-300">
            Backup History
          </h2>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 bg-slate-700 border border-slate-600 rounded-md
                       text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-phosphor-500"
          >
            <option value="">All</option>
            <option value="completed">Completed</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        {backupsLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
          </div>
        ) : backupsError ? (
          <div className="p-6 bg-rose-500/10 border border-rose-500/30 rounded-lg text-center">
            <AlertCircle className="w-8 h-8 text-rose-400 mx-auto mb-3" />
            <p className="text-rose-400">Failed to load backups</p>
            <button
              type="button"
              onClick={() => refetchBackups()}
              className="mt-3 text-sm text-slate-400 hover:text-slate-200"
            >
              Try again
            </button>
          </div>
        ) : backups.length === 0 ? (
          <div className="p-12 bg-slate-800/50 rounded-lg border border-slate-700 text-center">
            <Archive className="w-12 h-12 text-slate-500 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-slate-300 mb-2">
              No backups found
            </h3>
            <p className="text-slate-400">
              {statusFilter
                ? `No backups with status "${statusFilter}"`
                : 'Create your first backup using the button above.'}
            </p>
          </div>
        ) : (
          <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/80">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-8" />
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Size
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {backups.map((backup) => {
                  const isExpanded = expandedId === backup.id
                  const source = sourceMap[backup.source_id]
                  return (
                    <Fragment key={backup.id}>
                      <tr
                        className={clsx(
                          'hover:bg-slate-700/30 transition-colors cursor-pointer',
                          isExpanded && 'bg-slate-700/20',
                        )}
                        onClick={() =>
                          setExpandedId(isExpanded ? null : backup.id)
                        }
                      >
                        <td className="px-4 py-3">
                          <ChevronDown
                            className={clsx(
                              'w-4 h-4 text-slate-500 transition-transform',
                              isExpanded && 'rotate-180',
                            )}
                          />
                        </td>
                        <td className="px-4 py-3">
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
                        <td className="px-4 py-3">
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
                                  <ShieldCheck className="w-3.5 h-3.5 text-green-400" />
                                ) : (
                                  <ShieldX className="w-3.5 h-3.5 text-red-400" />
                                )}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={clsx(
                              'text-xs px-2 py-0.5 rounded-full',
                              backup.backup_type === 'scheduled'
                                ? 'bg-indigo-500/20 text-indigo-400'
                                : 'bg-slate-600 text-slate-300',
                            )}
                          >
                            {backup.backup_type}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-300">
                          {formatBytes(backup.size_bytes)}
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-400">
                          {formatDate(backup.created_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div
                            className="flex items-center justify-end gap-2"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Link
                              href={`/backups/${backup.source_id}`}
                              className="p-1.5 text-slate-400 hover:text-phosphor-400 transition-colors"
                              title="View Source"
                            >
                              <Eye className="w-4 h-4" />
                            </Link>
                            {backup.status === 'completed' && (
                              <Link
                                href={`/backups/${backup.source_id}/restore/${backup.id}`}
                                className="p-1.5 text-slate-400 hover:text-yellow-400 transition-colors"
                                title="Restore"
                              >
                                <RotateCcw className="w-4 h-4" />
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
    </main>
  )
}
