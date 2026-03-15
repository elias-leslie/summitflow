'use client'

import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, AlertTriangle, XCircle, Loader2, Activity, Upload, ShieldCheck } from 'lucide-react'
import { clsx } from 'clsx'
import { type BackupHealthItem, type BackupHealthResponse, fetchBackupHealth } from '@/lib/api/backups'
import { formatDate } from '@/lib/format'

const HEALTH_ICONS = {
  green: CheckCircle2,
  yellow: AlertTriangle,
  red: XCircle,
} as const

const HEALTH_STYLES = {
  green: 'border-green-500/30 bg-green-500/5',
  yellow: 'border-amber-500/30 bg-amber-500/5',
  red: 'border-red-500/30 bg-red-500/5',
} as const

const HEALTH_ICON_STYLES = {
  green: 'text-green-400',
  yellow: 'text-amber-400',
  red: 'text-red-400',
} as const

const SOURCE_TYPE_LABELS: Record<string, string> = {
  project: 'Project',
  config: 'Config',
  workspace: 'Workspace',
  infrastructure: 'Infrastructure',
}

export function HealthCard({ item, action }: { item: BackupHealthItem; action?: React.ReactNode }) {
  const status = item.health_status as keyof typeof HEALTH_ICONS
  const Icon = HEALTH_ICONS[status] ?? AlertTriangle
  const style = HEALTH_STYLES[status] ?? HEALTH_STYLES.yellow
  const iconStyle = HEALTH_ICON_STYLES[status] ?? HEALTH_ICON_STYLES.yellow

  return (
    <div className={clsx('p-3 rounded-lg border', style)}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={clsx('w-4 h-4', iconStyle)} />
        <span className="text-sm font-medium text-slate-200 truncate">{item.source_name}</span>
        <span className="ml-auto text-[10px] text-slate-500 shrink-0">
          {SOURCE_TYPE_LABELS[item.source_type] ?? item.source_type}
        </span>
      </div>
      <div className="space-y-0.5 text-xs text-slate-400">
        {item.last_success_at ? (
          <div>Last backup: {formatDate(item.last_success_at)}</div>
        ) : (
          <div className="text-amber-400">No successful backups yet</div>
        )}
        {item.next_run_at && item.enabled && (
          <div>Next: {formatDate(item.next_run_at)}</div>
        )}
        {item.failure_count_7d > 0 && (
          <div className="text-red-400">
            {item.failure_count_7d} failure{item.failure_count_7d > 1 ? 's' : ''} (7d)
          </div>
        )}
        {item.pending_upload_count > 0 && (
          <div className="flex items-center gap-1 text-amber-400">
            <Upload className="w-3 h-3" />
            {item.pending_upload_count} pending upload{item.pending_upload_count > 1 ? 's' : ''}
          </div>
        )}
        {item.last_restore_tested_at ? (
          <div className={clsx('flex items-center gap-1', item.last_restore_test_ok ? 'text-green-400' : 'text-red-400')}>
            <ShieldCheck className="w-3 h-3" />
            Restore {item.last_restore_test_ok ? 'OK' : 'failed'}: {formatDate(item.last_restore_tested_at)}
          </div>
        ) : (
          <div className="text-slate-500 flex items-center gap-1">
            <ShieldCheck className="w-3 h-3" />
            Restore never tested
          </div>
        )}
        {!item.enabled && (
          <div className="text-slate-500">Scheduling disabled</div>
        )}
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** i).toFixed(i > 0 ? 1 : 0)} ${units[i]}`
}

interface BackupHealthDashboardProps {
  sources?: BackupHealthItem[]
}

export function BackupHealthDashboard({ sources: externalSources }: BackupHealthDashboardProps) {
  const { data, isLoading, error } = useQuery<BackupHealthResponse>({
    queryKey: ['backup-health'],
    queryFn: fetchBackupHealth,
    refetchInterval: 30_000,
    enabled: !externalSources,
  })

  const sources = externalSources ?? data?.sources

  if (!externalSources && isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 py-4">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading health status...
      </div>
    )
  }

  if ((!externalSources && error) || !sources?.length) {
    return null
  }

  const greenCount = sources.filter(s => s.health_status === 'green').length
  const yellowCount = sources.filter(s => s.health_status === 'yellow').length
  const redCount = sources.filter(s => s.health_status === 'red').length
  const pendingUploadCount = data?.pending_upload_count ?? 0
  const wal = data?.wal

  return (
    <section className="mb-8">
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-4 h-4 text-slate-400" />
        <h2 className="text-sm font-medium text-slate-300">Backup Health</h2>
        <div className="flex items-center gap-3 ml-4 text-xs text-slate-500">
          {greenCount > 0 && (
            <span className="flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3 text-green-400" />{greenCount}
            </span>
          )}
          {yellowCount > 0 && (
            <span className="flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-400" />{yellowCount}
            </span>
          )}
          {redCount > 0 && (
            <span className="flex items-center gap-1">
              <XCircle className="w-3 h-3 text-red-400" />{redCount}
            </span>
          )}
          {pendingUploadCount > 0 && (
            <span className="flex items-center gap-1 text-amber-400">
              <Upload className="w-3 h-3" />{pendingUploadCount} pending
            </span>
          )}
        </div>
      </div>

      {wal && (
        <div className="mb-3 p-2 rounded border border-slate-700/50 bg-slate-800/30 text-xs text-slate-400 flex items-center gap-4">
          <span className={clsx('font-medium', wal.enabled ? 'text-green-400' : 'text-slate-500')}>
            WAL: {wal.enabled ? 'ON' : 'OFF'}
          </span>
          {wal.archive_segment_count > 0 && (
            <span>{wal.archive_segment_count} segments ({formatBytes(wal.archive_size_bytes)})</span>
          )}
          {wal.last_archived_time && (
            <span>Last: {formatDate(wal.last_archived_time)}</span>
          )}
          {(wal.failed_count ?? 0) > 0 && (
            <span className="text-red-400">{wal.failed_count} failed</span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {sources.map(item => (
          <HealthCard key={item.source_id} item={item} />
        ))}
      </div>
    </section>
  )
}
