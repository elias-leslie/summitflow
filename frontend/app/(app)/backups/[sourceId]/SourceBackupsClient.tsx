'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Archive,
  ArrowLeft,
  ChevronDown,
  Database,
  FileCheck,
  FolderOpen,
  HardDrive,
  Loader2,
  Plus,
  RotateCcw,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'
import Link from 'next/link'
import { Fragment, useRef, useState } from 'react'
import { BackupScheduleConfig } from '@/components/backup/BackupScheduleConfig'
import { StatusBadge } from '@/components/backup/StatusBadge'
import {
  type Backup,
  type BackupSource,
  backupHasDatabase,
  createSourceBackup,
  fetchBackupSource,
  fetchSourceBackups,
  fetchStorageSummary,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

const SOURCE_TYPE_STYLES: Record<string, string> = {
  project: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  config: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  workspace: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  infrastructure: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
}

function SourceTypeBadge({ type }: { type: BackupSource['source_type'] }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border leading-none',
        SOURCE_TYPE_STYLES[type] ?? 'bg-slate-600 text-slate-300 border-slate-500',
      )}
    >
      {type}
    </span>
  )
}

function BackupExpandedRow({ backup }: { backup: Backup }) {
  const hasDatabase = backupHasDatabase(backup)

  return (
    <tr>
      <td colSpan={6} className="px-4 py-0">
        <div className="py-4 pl-6 border-l-2 border-slate-600 ml-2 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Type</p>
              <p className="text-slate-200">{backup.backup_type}</p>
            </div>
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Location</p>
              <p className="text-slate-200 truncate">{backup.location || '-'}</p>
            </div>
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Name</p>
              <p className="text-slate-200 font-mono text-xs truncate">{backup.name || '-'}</p>
            </div>
            <div>
              <p className="text-slate-500 text-xs mb-0.5">ID</p>
              <p className="text-slate-200 font-mono text-xs truncate">{backup.id}</p>
            </div>
          </div>

          {(hasDatabase || backup.files_size_bytes != null) && (
            <div className="flex items-center gap-6 text-sm">
              {hasDatabase && backup.db_size_bytes != null && (
                <div className="flex items-center gap-2">
                  <Database className="w-3.5 h-3.5 text-blue-400" />
                  <span className="text-slate-400">Database:</span>
                  <span className="text-slate-200">{formatBytes(backup.db_size_bytes)}</span>
                </div>
              )}
              {backup.files_size_bytes != null && (
                <div className="flex items-center gap-2">
                  <HardDrive className="w-3.5 h-3.5 text-purple-400" />
                  <span className="text-slate-400">Files:</span>
                  <span className="text-slate-200">{formatBytes(backup.files_size_bytes)}</span>
                </div>
              )}
              {!hasDatabase && (
                <div className="flex items-center gap-2">
                  <HardDrive className="w-3.5 h-3.5 text-purple-400" />
                  <span className="text-slate-400">Backup:</span>
                  <span className="text-slate-200">Files only</span>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center gap-6 text-sm">
            {backup.started_at && (
              <div>
                <span className="text-slate-500">Started: </span>
                <span className="text-slate-300">{formatDate(backup.started_at)}</span>
              </div>
            )}
            {backup.completed_at && (
              <div>
                <span className="text-slate-500">Completed: </span>
                <span className="text-slate-300">{formatDate(backup.completed_at)}</span>
              </div>
            )}
            {backup.started_at && backup.completed_at && (
              <div>
                <span className="text-slate-500">Duration: </span>
                <span className="text-slate-300">
                  {Math.round(
                    (new Date(backup.completed_at).getTime() -
                      new Date(backup.started_at).getTime()) /
                      1000,
                  )}
                  s
                </span>
              </div>
            )}
          </div>

          {backup.note && (
            <div className="text-sm">
              <span className="text-slate-500">Note: </span>
              <span className="text-slate-300">{backup.note}</span>
            </div>
          )}

          {backup.verified != null && (
            <div
              className={clsx(
                'p-3 rounded-lg border',
                backup.verified
                  ? 'bg-green-500/10 border-green-500/30'
                  : 'bg-red-500/10 border-red-500/30',
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                {backup.verified ? (
                  <ShieldCheck className="w-4 h-4 text-green-400" />
                ) : (
                  <ShieldX className="w-4 h-4 text-red-400" />
                )}
                <span
                  className={clsx(
                    'text-sm font-medium',
                    backup.verified ? 'text-green-400' : 'text-red-400',
                  )}
                >
                  {backup.verified ? 'Verified' : 'Verification Failed'}
                </span>
                {backup.verified_at && (
                  <span className="text-xs text-slate-500 ml-auto">
                    {formatDate(backup.verified_at)}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
                {backup.checksum && (
                  <div>
                    <p className="text-slate-500 text-xs mb-0.5">Checksum</p>
                    <p className="text-slate-300 font-mono text-xs truncate" title={backup.checksum}>
                      {backup.checksum}
                    </p>
                  </div>
                )}
                {backup.total_files != null && (
                  <div>
                    <p className="text-slate-500 text-xs mb-0.5">Files</p>
                    <p className="text-slate-300 flex items-center gap-1">
                      <FileCheck className="w-3 h-3 text-slate-500" />
                      {backup.total_files.toLocaleString()}
                    </p>
                  </div>
                )}
              </div>
              {backup.verification_json?.tree && Object.keys(backup.verification_json.tree).length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-700/50">
                  <p className="text-xs text-slate-500 mb-1">Archive Contents</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-0.5">
                    {Object.entries(backup.verification_json.tree)
                      .sort(([, a], [, b]) => b.count - a.count)
                      .map(([name, info]) => (
                        <div key={name} className="flex items-center justify-between text-xs">
                          <span className="text-slate-400 truncate">{name}</span>
                          <span className="text-slate-500 ml-2">{info.count}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
              {backup.verification_json?.errors && backup.verification_json.errors.length > 0 && (
                <div className="mt-2 pt-2 border-t border-red-500/20">
                  {backup.verification_json.errors.map((err) => (
                    <p key={err} className="text-xs text-red-400">{err}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {backup.status === 'failed' && backup.error_message && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
              <p className="text-xs text-red-400 font-medium mb-1">Error</p>
              <p className="text-sm text-red-300 whitespace-pre-wrap">{backup.error_message}</p>
            </div>
          )}
        </div>
      </td>
    </tr>
  )
}

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
    refetchInterval: (query) => {
      const backups = query.state.data?.backups
      if (!backups) return 10000
      const hasActive = backups.some(
        (b) => b.status === 'pending' || b.status === 'running',
      )
      const recentlyDispatched = Date.now() - dispatchedAtRef.current < 30_000
      return hasActive || recentlyDispatched ? 3000 : false
    },
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
      await queryClient.invalidateQueries({ queryKey: ['source-backups', sourceId] })
      await queryClient.invalidateQueries({ queryKey: ['storage-summary', sourceId] })
      setShowCreateForm(false)
      setCreateNote('')
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : 'Failed to create backup',
      )
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
        {backupsLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
          </div>
        ) : backupsError ? (
          <div className="p-6 bg-red-500/10 border border-red-500/30 rounded-lg text-center">
            <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
            <p className="text-red-400">Failed to load backups</p>
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
              No backups yet
            </h3>
            <p className="text-slate-400">
              {statusFilter
                ? `No backups with status "${statusFilter}"`
                : 'Create the first backup for this source.'}
            </p>
          </div>
        ) : (
          <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/80">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-8" />
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
                          <div className="flex items-center gap-1.5">
                            <StatusBadge status={backup.status} />
                            {backup.verified != null && (
                              <span title={backup.verified ? 'Verified' : 'Verification failed'}>
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
                            {backup.status === 'completed' && (
                              <Link
                                href={`/backups/${source.id}/restore/${backup.id}`}
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
                        <BackupExpandedRow backup={backup} />
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
