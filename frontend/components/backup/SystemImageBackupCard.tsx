'use client'

import { clsx } from 'clsx'
import {
  CheckCircle2,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
  Square,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { CollapsibleSection } from '@/components/backup/CollapsibleSection'
import {
  type SystemImageBackupStatus,
  startSystemImageBackup,
  stopSystemImageBackup,
} from '@/lib/api/backups'

interface SystemImageBackupCardProps {
  status: SystemImageBackupStatus | undefined
  isLoading: boolean
  onRefresh: () => void
}

function statusTone(status: SystemImageBackupStatus | undefined) {
  if (!status) return 'text-slate-400'
  if (status.active_session) return 'text-blue-400'
  if (status.blocked_reason) return 'text-amber-400'
  if (status.last_session?.state === 'Failed') return 'text-rose-400'
  return 'text-emerald-400'
}

function statusLabel(status: SystemImageBackupStatus | undefined) {
  if (!status) return 'Loading'
  if (status.active_session) return status.active_session.state
  if (status.mok_enrollment_pending) return 'Reboot Required'
  if (status.blocked_reason) return 'Blocked'
  if (status.last_session?.state === 'Failed') return 'Needs Retry'
  return 'Ready'
}

function summary(
  status: SystemImageBackupStatus | undefined,
  isLoading: boolean,
) {
  if (isLoading) return 'Loading Veeam system-image status.'
  if (!status) return 'System-image status unavailable.'
  if (status.active_session) {
    return `${status.active_session.state} since ${status.active_session.started_at ?? status.active_session.created_at ?? 'unknown time'}`
  }
  if (status.blocked_reason) return status.blocked_reason
  return `${status.repository_name}, ${status.schedule_summary ?? 'schedule configured'}`
}

export function SystemImageBackupCard({
  status,
  isLoading,
  onRefresh,
}: SystemImageBackupCardProps) {
  const [action, setAction] = useState<'start' | 'stop' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const runAction = async (kind: 'start' | 'stop') => {
    setAction(kind)
    setActionError(null)
    try {
      if (kind === 'start') {
        await startSystemImageBackup()
      } else {
        await stopSystemImageBackup()
      }
      onRefresh()
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : `Failed to ${kind} backup`,
      )
    }
    setAction(null)
  }

  return (
    <CollapsibleSection
      title="System Image"
      titleAccessory={
        <span
          className={clsx(
            'text-[10px] uppercase tracking-[0.14em]',
            statusTone(status),
          )}
        >
          {statusLabel(status)}
        </span>
      }
      summary={summary(status, isLoading)}
      contentClassName="border-t border-slate-800/40 px-4 py-4 space-y-3"
    >
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-phosphor-400" />
          Loading system-image status
        </div>
      ) : status ? (
        <>
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            <StatusCell
              label="Veeam"
              value={
                status.installed ? (status.version ?? 'Installed') : 'Missing'
              }
              ok={status.installed && status.service_active}
            />
            <StatusCell
              label="Secure Boot"
              value={
                status.secure_boot_enabled
                  ? status.mok_enrolled
                    ? 'Enrolled'
                    : status.mok_enrollment_pending
                      ? 'Pending'
                      : 'Blocked'
                  : 'Disabled'
              }
              ok={!status.secure_boot_enabled || status.mok_enrolled}
            />
            <StatusCell
              label="Kernel Module"
              value={
                status.module_loaded
                  ? 'Loaded'
                  : (status.module_signer ?? 'Not loaded')
              }
              ok={status.module_loaded || status.mok_enrollment_pending}
            />
            <StatusCell
              label="Repository"
              value={
                status.repository_accessible
                  ? status.repository_name
                  : 'Unavailable'
              }
              ok={status.repository_accessible}
            />
            <StatusCell
              label="Job"
              value={
                status.job_configured
                  ? (status.schedule_summary ?? 'Configured')
                  : 'Missing'
              }
              ok={status.job_configured}
            />
            <StatusCell
              label="Last Session"
              value={
                status.last_session
                  ? `${status.last_session.state} ${status.last_session.finished_at ?? ''}`.trim()
                  : 'None'
              }
              ok={status.last_session?.state !== 'Failed'}
            />
          </div>

          <div className="rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Location
            </div>
            <div className="truncate font-mono text-xs text-slate-200">
              {status.repository_path}
            </div>
          </div>

          {status.protected_objects.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {status.protected_objects.map((object) => (
                <span
                  key={object}
                  className="rounded border border-slate-700/60 bg-slate-800/50 px-1.5 py-0.5 font-mono text-[10px] text-slate-300"
                >
                  {object}
                </span>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => runAction('start')}
              disabled={!status.can_start || action != null}
              className="flex items-center gap-1.5 rounded bg-emerald-500/10 px-2.5 py-1 text-2xs text-emerald-400 transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
            >
              {action === 'start' ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              Start
            </button>
            <button
              type="button"
              onClick={() => runAction('stop')}
              disabled={!status.active_session || action != null}
              className="flex items-center gap-1.5 rounded bg-rose-500/10 px-2.5 py-1 text-2xs text-rose-400 transition-colors hover:bg-rose-500/20 disabled:opacity-40"
            >
              {action === 'stop' ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Square className="h-3 w-3" />
              )}
              Stop
            </button>
            <button
              type="button"
              onClick={onRefresh}
              disabled={action != null}
              className="flex items-center gap-1.5 rounded bg-slate-700/50 px-2.5 py-1 text-2xs text-slate-400 transition-colors hover:bg-slate-700/80 disabled:opacity-40"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh
            </button>
          </div>

          {(status.blocked_reason || actionError) && (
            <div className="flex items-start gap-2 rounded border border-amber-500/20 bg-amber-500/8 px-2.5 py-2 text-xs text-amber-300">
              <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{actionError ?? status.next_action}</span>
            </div>
          )}
        </>
      ) : (
        <div className="text-xs text-rose-400">
          System-image status unavailable.
        </div>
      )}
    </CollapsibleSection>
  )
}

function StatusCell({
  label,
  value,
  ok,
}: {
  label: string
  value: string
  ok: boolean
}) {
  return (
    <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
        {ok ? (
          <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
        ) : (
          <XCircle className="h-3 w-3 shrink-0 text-amber-400" />
        )}
        <span className="truncate text-xs text-slate-200">{value}</span>
      </div>
    </div>
  )
}
