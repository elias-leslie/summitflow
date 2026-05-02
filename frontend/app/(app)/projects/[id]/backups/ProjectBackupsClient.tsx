'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Archive,
  ArrowLeft,
  HardDrive,
  Loader2,
  Plus,
  RotateCcw,
  Trash2,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { useRef, useState } from 'react'
import {
  type BackupColumn,
  BackupHistoryTable,
} from '@/components/backup/BackupHistoryTable'
import { BackupScheduleConfig } from '@/components/backup/BackupScheduleConfig'
import { activeBackupRefetchInterval } from '@/components/backup/backupPolling'
import { fetchProject } from '@/lib/api'
import {
  type Backup,
  createBackup,
  deleteBackup,
  fetchBackups,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'
import { getErrorMessage } from '@/lib/utils'

const PROJECT_BACKUP_COLUMNS: BackupColumn[] = [
  {
    key: 'size',
    label: 'Size',
    render: (backup) => (
      <div className="flex items-center gap-2 text-sm text-slate-300">
        <HardDrive className="w-3.5 h-3.5 text-slate-500" />
        {formatBytes(backup.size_bytes)}
      </div>
    ),
  },
  {
    key: 'created',
    label: 'Created',
    className: 'text-sm text-slate-400',
    render: (backup) => formatDate(backup.created_at),
  },
  {
    key: 'note',
    label: 'Note',
    className: 'text-sm text-slate-400 max-w-[200px] truncate',
    render: (backup) => backup.note || '-',
  },
]

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
    refetchInterval: (query) =>
      activeBackupRefetchInterval(query, dispatchedAtRef.current),
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
            <h1 className="text-2xl font-semibold text-slate-100 display flex items-center gap-3">
              <Archive className="w-6 h-6 text-slate-400" />
              Backups
            </h1>
            <p className="text-sm text-slate-400 mt-1">{project.name}</p>
          </div>
          <button
            type="button"
            onClick={() => setCreateDialogOpen(true)}
            className="btn-primary flex items-center gap-2 text-sm"
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
        <BackupHistoryTable
          backups={backups}
          isLoading={backupsLoading}
          hasError={Boolean(backupsError)}
          onRetry={() => refetchBackups()}
          emptyState={
            <div className="p-12 bg-slate-800/50 rounded-lg border border-dashed border-slate-700 text-center">
              <div className="mx-auto mb-5 w-16 h-16 rounded-2xl bg-indigo-500/8 border border-indigo-500/15 flex items-center justify-center">
                <Archive className="w-8 h-8 text-indigo-500/50" />
              </div>
              <h3 className="text-lg font-medium text-slate-200 mb-2 display">
                No backups yet
              </h3>
              <p className="text-sm text-slate-500 mb-6 max-w-xs mx-auto">
                Create your first backup to protect your project data. Scheduled
                backups can also be configured above.
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
          }
          expandedId={expandedId}
          onToggleExpanded={setExpandedId}
          columns={PROJECT_BACKUP_COLUMNS}
          renderActions={(backup: Backup) => (
            <>
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
            </>
          )}
          getExpandedSourceName={() => project.name}
          getExpandedSourceType={() => 'project'}
        />
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
                onClick={() => {
                  setDeleteConfirmId(null)
                  setDeleteError(null)
                }}
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
