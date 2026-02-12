'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Archive,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Database,
  Eye,
  FileCheck,
  HardDrive,
  Loader2,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  ShieldX,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import { Fragment, useMemo, useState } from 'react'
import { StatusBadge } from '@/components/backup/StatusBadge'
import {
  type Backup,
  createBackup,
  fetchAllBackups,
  fetchBackupSchedule,
  fetchStorageSummary,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'
import { fetchProjects, type Project } from '@/lib/api/projects'

interface CreateBackupModalProps {
  projects: Project[]
  onClose: () => void
  onCreated: () => Promise<void>
}

function CreateBackupModal({
  projects,
  onClose,
  onCreated,
}: CreateBackupModalProps) {
  const [selectedProjects, setSelectedProjects] = useState<Set<string>>(new Set())
  const [note, setNote] = useState<string>('')
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleProject = (id: string) => {
    setSelectedProjects((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selectedProjects.size === projects.length) {
      setSelectedProjects(new Set())
    } else {
      setSelectedProjects(new Set(projects.map((p) => p.id)))
    }
  }

  const handleCreate = async () => {
    setIsPending(true)
    setError(null)
    try {
      await Promise.all(
        Array.from(selectedProjects).map((projectId) =>
          createBackup(projectId, { note: note || undefined }),
        ),
      )
      await onCreated()
      onClose()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to create backups. Please try again.',
      )
    } finally {
      setIsPending(false)
    }
  }

  const count = selectedProjects.size

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      data-testid="backup-create-modal"
    >
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-100 mb-4">
          Create Manual Backup
        </h2>

        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-slate-300">
                Select Projects
              </span>
              <button
                onClick={toggleAll}
                className="text-xs text-phosphor-400 hover:text-phosphor-300 transition-colors"
              >
                {selectedProjects.size === projects.length ? 'Deselect all' : 'Select all'}
              </button>
            </div>
            <div
              className="max-h-48 overflow-y-auto rounded-md border border-slate-600 bg-slate-700 divide-y divide-slate-600/50"
              data-testid="backup-project-select"
            >
              {projects.map((p) => (
                <label
                  key={p.id}
                  className="flex items-center gap-3 px-3 py-2 hover:bg-slate-600/40 cursor-pointer transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedProjects.has(p.id)}
                    onChange={() => toggleProject(p.id)}
                    className="rounded border-slate-500 bg-slate-600 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0"
                  />
                  <span className="text-sm text-slate-200">{p.name}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label
              htmlFor="backup-note"
              className="block text-sm text-slate-300 mb-2"
            >
              Note (optional)
            </label>
            <input
              id="backup-note"
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g., Before major refactor"
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md
                         text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-phosphor-500"
              data-testid="backup-note-input"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={count === 0 || isPending}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-sm rounded-md font-medium transition-colors',
              count > 0 && !isPending
                ? 'bg-phosphor-600 text-white hover:bg-phosphor-500'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed',
            )}
            data-testid="backup-create-confirm"
          >
            {isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                {count > 1
                  ? `Create ${count} Backups`
                  : 'Create Backup'}
              </>
            )}
          </button>
        </div>

        {error && (
          <p className="mt-3 text-sm text-red-400">{error}</p>
        )}
      </div>
    </div>
  )
}

interface ScheduleCardProps {
  projectId: string
  projectName: string
}

function ScheduleCard({ projectId, projectName }: ScheduleCardProps) {
  const { data: schedule, isLoading } = useQuery({
    queryKey: ['backup-schedule', projectId],
    queryFn: () => fetchBackupSchedule(projectId),
  })

  if (isLoading) {
    return (
      <div className="p-4 bg-slate-700/30 rounded-lg animate-pulse">
        <div className="h-4 bg-slate-600 rounded w-1/3 mb-2" />
        <div className="h-3 bg-slate-600 rounded w-1/2" />
      </div>
    )
  }

  if (!schedule) {
    return (
      <div className="p-4 bg-slate-700/30 rounded-lg border border-slate-600/50">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-200">{projectName}</p>
            <p className="text-xs text-slate-500 mt-0.5">
              No schedule configured
            </p>
          </div>
          <Link
            href={`/projects/${projectId}/backups?from=backups`}
            className="text-xs text-phosphor-400 hover:text-phosphor-300"
          >
            Configure
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div
      className={clsx(
        'p-4 rounded-lg border',
        schedule.enabled
          ? 'bg-green-500/5 border-green-500/20'
          : 'bg-slate-700/30 border-slate-600/50',
      )}
      data-testid={`schedule-card-${projectId}`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {schedule.enabled ? (
            <Power className="w-4 h-4 text-green-400" />
          ) : (
            <PowerOff className="w-4 h-4 text-slate-500" />
          )}
          <p className="text-sm font-medium text-slate-200">{projectName}</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full',
              schedule.enabled
                ? 'bg-green-500/20 text-green-400'
                : 'bg-slate-600 text-slate-400',
            )}
          >
            {schedule.enabled ? schedule.frequency : 'disabled'}
          </span>
          <Link
            href={`/projects/${projectId}/backups?from=backups`}
            className="text-xs text-phosphor-400 hover:text-phosphor-300"
          >
            Edit
          </Link>
        </div>
      </div>
      {schedule.enabled && (
        <div className="text-xs text-slate-400 space-y-1">
          <p className="flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            Next:{' '}
            {schedule.next_run_at
              ? formatDate(schedule.next_run_at)
              : 'Not scheduled'}
          </p>
          <p>Retention: {schedule.retention_days} days</p>
        </div>
      )}
    </div>
  )
}

function BackupExpandedRow({ backup, projectName }: { backup: Backup; projectName: string }) {
  return (
    <tr>
      <td colSpan={7} className="px-4 py-0">
        <div className="py-4 pl-6 border-l-2 border-slate-600 ml-2 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Project</p>
              <p className="text-slate-200">{projectName}</p>
            </div>
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
          </div>

          {(backup.db_size_bytes || backup.files_size_bytes) && (
            <div className="flex items-center gap-6 text-sm">
              {backup.db_size_bytes != null && (
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

export function BackupsClient() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showSchedules, setShowSchedules] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  const projectMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const p of projects) {
      map[p.id] = p.name
    }
    return map
  }, [projects])

  const {
    data: backupsData,
    isLoading: backupsLoading,
    error: backupsError,
    refetch: refetchBackups,
  } = useQuery({
    queryKey: ['all-backups', statusFilter],
    queryFn: () =>
      fetchAllBackups({
        limit: 100,
        status: statusFilter || undefined,
      }),
    refetchInterval: (query) => {
      const backups = query.state.data?.backups
      if (!backups) return 10000
      const hasActive = backups.some(
        (b) => b.status === 'pending' || b.status === 'running',
      )
      return hasActive ? 5000 : false
    },
  })

  const { data: storageSummary, isLoading: storageLoading } = useQuery({
    queryKey: ['storage-summary'],
    queryFn: () => fetchStorageSummary(),
  })

  const backups = backupsData?.backups ?? []

  const handleBackupCreated = async () => {
    await queryClient.invalidateQueries({ queryKey: ['all-backups'] })
    await queryClient.invalidateQueries({ queryKey: ['storage-summary'] })
  }

  return (
    <main className="content-container py-8">
      {showCreateModal && (
        <CreateBackupModal
          projects={projects}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleBackupCreated}
        />
      )}

      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-3">
            <Archive className="w-6 h-6 text-slate-400" />
            All Backups
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Overview of backups across all projects
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-phosphor-600 text-white rounded-md
                     text-sm font-medium hover:bg-phosphor-500 transition-colors"
          data-testid="backup-manual-trigger"
        >
          <Plus className="w-4 h-4" />
          Create Backup
        </button>
      </header>

      {/* Storage Summary Cards */}
      <section className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <Database className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-100">
                {storageLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  (storageSummary?.total_count ?? 0)
                )}
              </p>
              <p className="text-xs text-slate-400">Total Backups</p>
            </div>
          </div>
        </div>

        <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-500/20 rounded-lg">
              <HardDrive className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-100">
                {storageLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  formatBytes(storageSummary?.total_bytes ?? 0)
                )}
              </p>
              <p className="text-xs text-slate-400">Total Storage</p>
            </div>
          </div>
        </div>

        <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <CheckCircle2 className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-100">
                {storageLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  (storageSummary?.by_status?.completed ?? 0)
                )}
              </p>
              <p className="text-xs text-slate-400">Completed</p>
            </div>
          </div>
        </div>

        <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-500/20 rounded-lg">
              <RefreshCw className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-100">
                {storageLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  (storageSummary?.by_status?.pending ?? 0) +
                  (storageSummary?.by_status?.running ?? 0)
                )}
              </p>
              <p className="text-xs text-slate-400">In Progress</p>
            </div>
          </div>
        </div>

        <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-500/20 rounded-lg">
              <XCircle className="w-5 h-5 text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-100">
                {storageLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  (storageSummary?.by_status?.failed ?? 0)
                )}
              </p>
              <p className="text-xs text-slate-400">Failed</p>
            </div>
          </div>
        </div>
      </section>

      {/* Backup Schedules */}
      <section className="mb-8" data-testid="backup-schedules-section">
        <button
          onClick={() => setShowSchedules(!showSchedules)}
          className="flex items-center gap-2 text-sm text-slate-300 hover:text-slate-100 mb-4"
        >
          <Calendar className="w-4 h-4" />
          <span>Backup Schedules</span>
          <span
            className={clsx(
              'transition-transform',
              showSchedules ? 'rotate-180' : '',
            )}
          >
            ▼
          </span>
        </button>
        {showSchedules && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((project) => (
              <ScheduleCard
                key={project.id}
                projectId={project.id}
                projectName={project.name}
              />
            ))}
          </div>
        )}
      </section>

      {/* Filters */}
      <section className="mb-6 flex items-center gap-4">
        <div>
          <label
            htmlFor="status-filter"
            className="block text-xs text-slate-400 mb-1"
          >
            Status
          </label>
          <select
            id="status-filter"
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
                : 'Create your first backup from a project page.'}
            </p>
          </div>
        ) : (
          <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/80">
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider w-8" />
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Project
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
                            href={`/projects/${backup.project_id}/backups?from=backups`}
                            className="text-sm text-phosphor-400 hover:text-phosphor-300"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {projectMap[backup.project_id] || backup.project_id}
                          </Link>
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
                            <Link
                              href={`/projects/${backup.project_id}/backups?from=backups`}
                              className="p-1.5 text-slate-400 hover:text-phosphor-400 transition-colors"
                              title="View in Project"
                            >
                              <Eye className="w-4 h-4" />
                            </Link>
                            {backup.status === 'completed' && (
                              <Link
                                href={`/projects/${backup.project_id}/backups/${backup.id}/restore`}
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
                          projectName={projectMap[backup.project_id] || backup.project_id}
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
