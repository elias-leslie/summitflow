'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  AlertCircle,
  Archive,
  Calendar,
  CheckCircle2,
  Clock,
  Database,
  Eye,
  HardDrive,
  Loader2,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  RotateCcw,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import {
  type Backup,
  createBackup,
  fetchAllBackups,
  fetchBackupSchedule,
  fetchStorageSummary,
} from '@/lib/api/backups'
import { fetchProjects, type Project } from '@/lib/api/projects'

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function StatusBadge({ status }: { status: Backup['status'] }) {
  const config = {
    pending: {
      icon: Clock,
      className: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    },
    running: {
      icon: RefreshCw,
      className: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    },
    completed: {
      icon: CheckCircle2,
      className: 'bg-green-500/20 text-green-400 border-green-500/30',
    },
    failed: {
      icon: XCircle,
      className: 'bg-red-500/20 text-red-400 border-red-500/30',
    },
  }[status]

  const Icon = config.icon

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
        config.className,
      )}
    >
      <Icon
        className={clsx('w-3 h-3', status === 'running' && 'animate-spin')}
      />
      {status}
    </span>
  )
}

interface CreateBackupModalProps {
  projects: Project[]
  onClose: () => void
  onCreated: () => void
}

function CreateBackupModal({
  projects,
  onClose,
  onCreated,
}: CreateBackupModalProps) {
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [note, setNote] = useState<string>('')

  const createMutation = useMutation({
    mutationFn: () =>
      createBackup(selectedProject, { note: note || undefined }),
    onSuccess: () => {
      onCreated()
      onClose()
    },
  })

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
            <label
              htmlFor="project-select"
              className="block text-sm text-slate-300 mb-2"
            >
              Select Project
            </label>
            <select
              id="project-select"
              value={selectedProject}
              onChange={(e) => setSelectedProject(e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md
                         text-slate-200 focus:outline-none focus:ring-2 focus:ring-phosphor-500"
              data-testid="backup-project-select"
            >
              <option value="">Choose a project...</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
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
            onClick={() => createMutation.mutate()}
            disabled={!selectedProject || createMutation.isPending}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-sm rounded-md font-medium transition-colors',
              selectedProject && !createMutation.isPending
                ? 'bg-phosphor-600 text-white hover:bg-phosphor-500'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed',
            )}
            data-testid="backup-create-confirm"
          >
            {createMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                Create Backup
              </>
            )}
          </button>
        </div>

        {createMutation.isError && (
          <p className="mt-3 text-sm text-red-400">
            Failed to create backup. Please try again.
          </p>
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
            href={`/projects/${projectId}/backups`}
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
            href={`/projects/${projectId}/backups`}
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
          <p>Retention: {schedule.retention_count} backups</p>
        </div>
      )}
    </div>
  )
}

export function BackupsClient() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showSchedules, setShowSchedules] = useState(false)

  // Fetch projects for the create modal and schedules
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  // Fetch all backups
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
    refetchInterval: 10000,
  })

  // Fetch storage summary
  const { data: storageSummary, isLoading: storageLoading } = useQuery({
    queryKey: ['storage-summary'],
    queryFn: () => fetchStorageSummary(),
  })

  const backups = backupsData?.backups ?? []

  const handleBackupCreated = () => {
    queryClient.invalidateQueries({ queryKey: ['all-backups'] })
    queryClient.invalidateQueries({ queryKey: ['storage-summary'] })
  }

  return (
    <main className="content-container py-8">
      {/* Create Backup Modal */}
      {showCreateModal && (
        <CreateBackupModal
          projects={projects}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleBackupCreated}
        />
      )}

      {/* Header */}
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
      <section className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
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
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Project
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Backup ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                    Status
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
                {backups.map((backup) => (
                  <tr
                    key={backup.id}
                    className="hover:bg-slate-700/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/projects/${backup.project_id}/backups`}
                        className="text-sm text-phosphor-400 hover:text-phosphor-300"
                      >
                        {backup.project_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm font-mono text-slate-200">
                        {backup.id}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={backup.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-300">
                      {formatBytes(backup.size_bytes)}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-400">
                      {formatDate(backup.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Link
                          href={`/projects/${backup.project_id}/backups`}
                          className="p-1.5 text-slate-400 hover:text-phosphor-400 transition-colors"
                          title="View Details"
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  )
}
