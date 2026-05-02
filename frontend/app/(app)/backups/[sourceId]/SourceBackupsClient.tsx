'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Archive,
  ArrowLeft,
  FolderOpen,
  Loader2,
  Plus,
  RotateCcw,
} from 'lucide-react'
import Link from 'next/link'
import { useRef, useState } from 'react'
import {
  type BackupColumn,
  BackupHistoryTable,
  BackupTypeBadge,
} from '@/components/backup/BackupHistoryTable'
import { BackupScheduleConfig } from '@/components/backup/BackupScheduleConfig'
import { activeBackupRefetchInterval } from '@/components/backup/backupPolling'
import { SourceTypeBadge } from '@/components/backup/SourceTypeBadge'
import { isAmbiguousDispatchError } from '@/lib/api/backup-dispatch'
import {
  type Backup,
  createSourceBackup,
  fetchBackupSource,
  fetchSourceBackups,
  fetchStorageSummary,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

const SOURCE_BACKUP_COLUMNS: BackupColumn[] = [
  {
    key: 'type',
    label: 'Type',
    render: (backup) => <BackupTypeBadge backupType={backup.backup_type} />,
  },
  {
    key: 'size',
    label: 'Size',
    className: 'text-sm text-slate-300',
    render: (backup) => formatBytes(backup.size_bytes),
  },
  {
    key: 'created',
    label: 'Created',
    className: 'text-sm text-slate-400',
    render: (backup) => formatDate(backup.created_at),
  },
]

export function SourceBackupsClient({ sourceId }: { sourceId: string }) {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [createNote, setCreateNote] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const dispatchedAtRef = useRef(0)

  const {
    data: source,
    isLoading: sourceLoading,
    error: sourceError,
  } = useQuery({
    queryKey: ['backup-source', sourceId],
    queryFn: () => fetchBackupSource(sourceId),
  })

  const {
    data: backupsData,
    isLoading: backupsLoading,
    error: backupsError,
    refetch: refetchBackups,
  } = useQuery({
    queryKey: ['source-backups', sourceId, statusFilter],
    queryFn: () =>
      fetchSourceBackups(sourceId, {
        limit: 100,
        status: statusFilter || undefined,
      }),
    refetchInterval: (query) =>
      activeBackupRefetchInterval(query, dispatchedAtRef.current),
  })

  const { data: storageSummary } = useQuery({
    queryKey: ['storage-summary', sourceId],
    queryFn: () => fetchStorageSummary(sourceId),
  })

  const backups = backupsData?.backups ?? []

  const handleCreate = async () => {
    setCreating(true)
    setCreateError(null)
    try {
      await createSourceBackup(sourceId, { note: createNote || undefined })
      dispatchedAtRef.current = Date.now()
      await queryClient.invalidateQueries({
        queryKey: ['source-backups', sourceId],
      })
      await queryClient.invalidateQueries({
        queryKey: ['storage-summary', sourceId],
      })
      setShowCreateForm(false)
      setCreateNote('')
    } catch (err) {
      const fallbackMessage = 'Failed to create backup'
      const message = err instanceof Error ? err.message : fallbackMessage

      if (isAmbiguousDispatchError(message)) {
        dispatchedAtRef.current = Date.now()
        await queryClient.invalidateQueries({
          queryKey: ['source-backups', sourceId],
        })
        await queryClient.invalidateQueries({
          queryKey: ['storage-summary', sourceId],
        })
        setCreateError(
          'Queue confirmation was lost while creating backup. It may still be queued. Check Backup History before retrying.',
        )
      } else {
        setCreateError(message)
      }
    } finally {
      setCreating(false)
    }
  }

  if (sourceLoading) {
    return (
      <main className="content-container py-8">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
        </div>
      </main>
    )
  }

  if (sourceError || !source) {
    return (
      <main className="content-container py-8">
        <div className="p-6 bg-red-500/10 border border-red-500/30 rounded-lg text-center">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
          <p className="text-red-400">Failed to load backup source</p>
          <Link
            href="/backups"
            className="mt-3 inline-block text-sm text-slate-400 hover:text-slate-200"
          >
            Back to all backups
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="content-container py-8">
      {/* Back link */}
      <Link
        href="/backups"
        className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        All Backups
      </Link>

      {/* Source Header */}
      <header className="mb-8 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-semibold text-slate-100 display">
              {source.name}
            </h1>
            <SourceTypeBadge type={source.source_type} />
          </div>
          <div className="flex items-center gap-4 text-sm text-slate-400">
            <span className="flex items-center gap-1.5">
              <FolderOpen className="w-3.5 h-3.5" />
              {source.path}
            </span>
            {storageSummary && (
              <>
                <span>{storageSummary.total_count} backups</span>
                <span>{formatBytes(storageSummary.total_bytes)}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {showCreateForm ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={createNote}
                onChange={(e) => setCreateNote(e.target.value)}
                placeholder="Note (optional)"
                className="px-3 py-1.5 bg-slate-700 border border-slate-600 rounded-md
                           text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-phosphor-500 w-48"
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              />
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-2 px-4 py-1.5 bg-phosphor-600 text-slate-50 rounded-md
                           text-sm font-medium hover:bg-phosphor-500 transition-colors disabled:opacity-50"
              >
                {creating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                Create
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateForm(false)
                  setCreateNote('')
                  setCreateError(null)
                }}
                className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowCreateForm(true)}
              className="flex items-center gap-2 px-4 py-2 bg-phosphor-600 text-slate-50 rounded-md
                         text-sm font-medium hover:bg-phosphor-500 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Create Backup
            </button>
          )}
        </div>
      </header>

      {createError && (
        <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
          <p className="text-sm text-red-400">{createError}</p>
        </div>
      )}

      {/* Schedule Config */}
      <section className="mb-8">
        <BackupScheduleConfig sourceId={sourceId} />
      </section>

      {/* Filters */}
      <section className="mb-6 flex items-center gap-4">
        <div>
          <label
            htmlFor="source-status-filter"
            className="block text-xs text-slate-400 mb-1"
          >
            Status
          </label>
          <select
            id="source-status-filter"
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
      </section>

      {/* Backup Table */}
      <section>
        <BackupHistoryTable
          backups={backups}
          isLoading={backupsLoading}
          hasError={Boolean(backupsError)}
          onRetry={() => refetchBackups()}
          emptyState={
            <div className="p-12 bg-slate-800/50 rounded-lg border border-slate-700 text-center">
              <Archive className="w-12 h-12 text-slate-500 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-slate-300 mb-2">
                No backups yet
              </h3>
              <p className="text-slate-400">
                {statusFilter
                  ? `No backups with status "${statusFilter}"`
                  : 'Create the first backup for this source.'}
              </p>
            </div>
          }
          expandedId={expandedId}
          onToggleExpanded={setExpandedId}
          columns={SOURCE_BACKUP_COLUMNS}
          renderActions={(backup: Backup) =>
            backup.status === 'completed' ? (
              <Link
                href={`/backups/${source.id}/restore/${backup.id}`}
                className="p-1.5 text-slate-400 hover:text-yellow-400 transition-colors"
                title="Restore"
              >
                <RotateCcw className="w-4 h-4" />
              </Link>
            ) : null
          }
          getExpandedSourceName={() => source.name}
          getExpandedSourceType={() => source.source_type}
        />
      </section>
    </main>
  )
}
