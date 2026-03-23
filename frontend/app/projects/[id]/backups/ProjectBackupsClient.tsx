'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Archive,
  ArrowLeft,
  ChevronDown,
  Database,
  FileCheck,
  HardDrive,
  Loader2,
  Plus,
  RotateCcw,
  ShieldCheck,
  ShieldX,
  Trash2,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { Fragment, useRef, useState } from 'react'
import { BackupScheduleConfig } from '@/components/backup/BackupScheduleConfig'
import { StatusBadge } from '@/components/backup/StatusBadge'
import { fetchProject } from '@/lib/api'
import {
  type Backup,
  backupHasDatabase,
  createBackup,
  deleteBackup,
  fetchBackups,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'
import { getErrorMessage } from '@/lib/utils'

function BackupExpandedRow({ backup }: { backup: Backup }) {
  const hasDatabase = backupHasDatabase(backup)

  return (
    <tr>
      <td colSpan={7} className="px-4 py-0">
        <div className="py-4 pl-6 border-l-2 border-slate-600 ml-2 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Type</p>
              <p className="text-slate-200">
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
              </p>
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
              <p className="text-slate-500 text-xs mb-0.5">Backup ID</p>
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

export function ProjectBackupsClient() {
  const params = useParams()
  const searchParams = useSearchParams()
  const projectId = params.id as string
  const cameFromBackups = searchParams.get('from') === 'backups'

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [backupNote, setBackupNote] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const dispatchedAtRef = useRef(0)

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  const {
    data: backupsData,
    isLoading: backupsLoading,
    error: backupsError,
    refetch: refetchBackups,
  } = useQuery({
    queryKey: ['backups', projectId],
    queryFn: () => fetchBackups(projectId),
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

  const backups = backupsData?.backups ?? []

  const handleCreateBackup = async () => {
    setCreating(true)
    setCreateError(null)
    try {
      await createBackup(projectId, { note: backupNote || undefined })
      dispatchedAtRef.current = Date.now()
      setCreateDialogOpen(false)
      setBackupNote('')
      refetchBackups()
    } catch (err) {
      setCreateError(getErrorMessage(err, 'Failed to create backup'))
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteBackup = async (backupId: string) => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteBackup(projectId, backupId)
      setDeleteConfirmId(null)
      refetchBackups()
    } catch (err) {
      setDeleteError(getErrorMessage(err, 'Failed to delete backup'))
    } finally {
      setDeleting(false)
    }
  }

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">Project not found</p>
        <Link href="/" className="text-blue-400 hover:text-blue-300">
          Back to dashboard
        </Link>
      </div>
    )
  }

  return (
    <main className="content-container py-8">
      <header className="mb-8">
        <div className="flex items-center gap-4 mb-4">
          <Link
            href={cameFromBackups ? '/backups' : `/projects/${projectId}`}
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-3">
              <Archive className="w-6 h-6 text-slate-400" />
              Backups
            </h1>
            <p className="text-sm text-slate-400 mt-1">{project.name}</p>
          </div>
          <button
            type="button"
            onClick={() => setCreateDialogOpen(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-phosphor-600 text-slate-50
                       hover:bg-phosphor-500 rounded-md transition-colors font-medium"
          >
            <Plus className="w-4 h-4" />
            Create Backup
          </button>
        </div>
      </header>

      <section className="mb-8">
        <BackupScheduleConfig sourceId={projectId} />
      </section>

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
          <div className="p-12 bg-slate-800/50 rounded-lg border border-dashed border-slate-700 text-center">
            <div className="mx-auto mb-5 w-16 h-16 rounded-2xl bg-indigo-500/8 border border-indigo-500/15 flex items-center justify-center">
              <Archive className="w-8 h-8 text-indigo-500/50" />
            </div>
            <h3 className="text-lg font-medium text-slate-200 mb-2 display">
              No backups yet
            </h3>
            <p className="text-sm text-slate-500 mb-6 max-w-xs mx-auto">
              Create your first backup to protect your project data. Scheduled backups can also be configured above.
            </p>
            <button
              type="button"
              onClick={() => setCreateDialogOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-phosphor-600 text-slate-50
                         hover:bg-phosphor-500 rounded-md transition-colors font-medium"
            >
              <Plus className="w-4 h-4" />
              Create Backup
            </button>
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
                    Size
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Note
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
                          <div className="flex items-center gap-2 text-sm text-slate-300">
                            <HardDrive className="w-3.5 h-3.5 text-slate-500" />
                            {formatBytes(backup.size_bytes)}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-400">
                          {formatDate(backup.created_at)}
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-400 max-w-[200px] truncate">
                          {backup.note || '-'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div
                            className="flex items-center justify-end gap-2"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {backup.status === 'completed' && (
                              <Link
                                href={`/projects/${projectId}/backups/${backup.id}/restore`}
                                className="p-1.5 text-slate-400 hover:text-phosphor-400 transition-colors"
                                title="Restore"
                              >
                                <RotateCcw className="w-4 h-4" />
                              </Link>
                            )}
                            <button
                              type="button"
                              onClick={() => setDeleteConfirmId(backup.id)}
                              className="p-1.5 text-slate-400 hover:text-red-400 transition-colors"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
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

      {createDialogOpen && (
        <div className="fixed inset-0 bg-slate-950/90 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md mx-4">
            <h3 className="text-lg font-semibold text-slate-100 mb-4 flex items-center gap-2">
              <Archive className="w-5 h-5 text-phosphor-400" />
              Create Backup
            </h3>
            <div className="space-y-4">
              <div>
                <label
                  htmlFor="backup-note"
                  className="block text-sm font-medium text-slate-300 mb-1"
                >
                  Note (optional)
                </label>
                <input
                  id="backup-note"
                  type="text"
                  value={backupNote}
                  onChange={(e) => setBackupNote(e.target.value)}
                  placeholder="e.g., Before major refactor"
                  className="input"
                />
              </div>

              {createError && (
                <p className="text-sm text-red-400">{createError}</p>
              )}

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setCreateDialogOpen(false)
                    setBackupNote('')
                    setCreateError(null)
                  }}
                  className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
                  disabled={creating}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleCreateBackup}
                  disabled={creating}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-phosphor-600 text-slate-50
                             hover:bg-phosphor-500 rounded-md transition-colors font-medium
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {creating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      Create
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {deleteConfirmId && (
        <div className="fixed inset-0 bg-slate-950/90 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md mx-4">
            <h3 className="text-lg font-semibold text-slate-100 mb-2 flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-red-400" />
              Delete Backup
            </h3>
            <p className="text-slate-400 mb-4">
              Are you sure you want to delete this backup? This action cannot be
              undone.
            </p>
            <p className="text-sm font-mono text-slate-300 bg-slate-700/50 px-3 py-2 rounded mb-4">
              {deleteConfirmId}
            </p>
            {deleteError && (
              <p className="text-xs text-rose-400 mono mb-3 px-3 py-2 bg-rose-500/10 rounded">
                {deleteError}
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => { setDeleteConfirmId(null); setDeleteError(null) }}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleDeleteBackup(deleteConfirmId)}
                disabled={deleting}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-red-600 text-slate-50
                           hover:bg-red-500 rounded-md transition-colors font-medium
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {deleting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    Delete
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
