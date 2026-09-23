'use client'

import { CloudUpload, Loader2, Square } from 'lucide-react'
import { useState } from 'react'
import {
  type BackupActivity,
  type BackupHealthItem,
  backupDriveFolderUrl,
  cancelBackup,
  syncBackupOffsite,
} from '@/lib/api/backups'
import { formatDate } from '@/lib/format'

const LABELS = {
  verified: 'Verified encrypted copy',
  pending: 'Not yet verified',
  failed: 'Sync failed',
  unconfigured: 'Not configured',
} as const

const PHASE_LABELS: Record<string, string> = {
  queued: 'Queued',
  capture: 'Capturing local files',
  encryption: 'Encrypting local backup',
  'local-storage': 'Saving local backup',
  upload: 'Uploading to Drive',
  verification: 'Verifying Drive copy',
  complete: 'Operation complete',
  cancelled: 'Operation cancelled',
  failed: 'Operation failed',
}

export function backupActivityLabel(activity: BackupActivity): string {
  if (activity.active && activity.cancel_requested) return 'Cancel requested'
  if (activity.active && activity.attention) {
    return activity.phase === 'upload' || activity.phase === 'verification'
      ? 'Waiting for Drive confirmation'
      : 'Progress unknown'
  }
  return PHASE_LABELS[activity.phase] ?? 'Backup operation'
}

export function OffsiteStatus({
  health,
  onSaved,
}: {
  health: BackupHealthItem
  onSaved: () => void
}) {
  const [syncing, setSyncing] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [cancelledRun, setCancelledRun] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState<{
    backupId: string
    previousRunId: string | null
  } | null>(null)
  const activity = health.backup_activity
  const active = activity?.active === true
  const awaitingDispatch =
    queued?.backupId === health.latest_backup_id &&
    queued?.previousRunId === (activity?.run_id ?? null)
  const cancelRequested =
    active &&
    (activity.cancel_requested ||
      (activity.run_id != null && cancelledRun === activity.run_id))
  const status = health.offsite_status ?? 'unconfigured'
  const driveFolderUrl = backupDriveFolderUrl(health.offsite_location)
  const handleSync = async () => {
    if (!health.latest_backup_id || active || awaitingDispatch || syncing)
      return
    setSyncing(true)
    setError(null)
    try {
      const result = await syncBackupOffsite(
        health.source_id,
        health.latest_backup_id,
      )
      if (result.status === 'queued') {
        setQueued({
          backupId: health.latest_backup_id,
          previousRunId: activity?.run_id ?? null,
        })
      }
      onSaved()
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : 'Could not sync this backup',
      )
    } finally {
      setSyncing(false)
    }
  }
  const handleCancel = async () => {
    if (!activity?.active || !activity.run_id || cancelling || cancelRequested)
      return
    setCancelling(true)
    setError(null)
    try {
      await cancelBackup(health.source_id, activity.backup_id, activity.run_id)
      setCancelledRun(activity.run_id)
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : 'Could not cancel this operation',
      )
    } finally {
      setCancelling(false)
      onSaved()
    }
  }

  return (
    <section
      aria-label="Backup recovery copies"
      className="space-y-2 rounded border border-slate-700/50 bg-slate-950/40 p-3 text-xs"
    >
      <dl className="grid gap-2 sm:grid-cols-3">
        <div>
          <dt className="text-slate-500">Last completed local backup</dt>
          <dd className="text-slate-200">
            {health.last_success_at
              ? formatDate(health.last_success_at)
              : 'No successful backup'}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Google Drive copy</dt>
          <dd
            className={
              status === 'verified' ? 'text-emerald-400' : 'text-amber-400'
            }
          >
            {LABELS[status]}
          </dd>
          {health.last_offsite_verified_at && (
            <dd className="text-slate-400">
              {formatDate(health.last_offsite_verified_at)}
            </dd>
          )}
        </div>
        <div>
          <dt className="text-slate-500">Isolated restore</dt>
          <dd className="text-slate-200">
            {health.last_isolated_restore_ok == null
              ? 'Not tested'
              : health.last_isolated_restore_ok
                ? 'Passed'
                : 'Failed'}
          </dd>
          {health.last_isolated_restore_at && (
            <dd className="text-slate-400">
              {formatDate(health.last_isolated_restore_at)}
            </dd>
          )}
        </div>
      </dl>
      {activity &&
        (active ||
          activity.phase === 'cancelled' ||
          activity.remote_outcome_unknown) && (
          <div className="space-y-1 border-t border-slate-700/50 pt-2">
            <p
              role="status"
              className={
                activity.attention ? 'text-amber-300' : 'text-slate-200'
              }
            >
              {cancelRequested
                ? 'Cancel requested'
                : backupActivityLabel(activity)}
            </p>
            {active && activity.operation_started_at && (
              <p className="text-slate-500">
                Started {formatDate(activity.operation_started_at)}
              </p>
            )}
            {active &&
              !cancelRequested &&
              (activity.phase === 'upload' ||
                activity.phase === 'verification') && (
                <p className="text-slate-400">
                  Transfer progress is unknown until Drive responds and the copy
                  is checked.
                  {activity.attention &&
                    ' A long wait does not prove the transfer has stalled. You can keep waiting or cancel.'}
                </p>
              )}
            {active &&
              !cancelRequested &&
              activity.attention &&
              activity.phase !== 'upload' &&
              activity.phase !== 'verification' && (
                <p className="text-slate-400">
                  The current operation has not reported progress. It is still
                  running; you can keep waiting or cancel.
                </p>
              )}
            {activity.verified_parts > 0 && (
              <p
                className="text-slate-400"
                title={activity.last_verified_part ?? undefined}
              >
                {activity.verified_parts}{' '}
                {activity.verified_parts === 1 ? 'part' : 'parts'} verified by
                download
                {activity.last_verified_at &&
                  `; last verified ${formatDate(activity.last_verified_at)}`}
                . This attempt is not fully verified yet.
              </p>
            )}
            {cancelRequested && (
              <p className="text-slate-400">
                Waiting for the worker to stop. Saved local backups and verified
                Drive parts are kept.
              </p>
            )}
            {activity.remote_outcome_unknown && (
              <p className="text-amber-300">
                Drive did not confirm whether the in-flight write finished. A
                retry checks existing parts before reusing them.
              </p>
            )}
            {active && activity.run_id && (
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelling || cancelRequested}
                className="inline-flex items-center gap-1.5 rounded bg-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-600 disabled:opacity-50"
              >
                <Square className="h-3 w-3" />
                {cancelRequested
                  ? 'Cancel requested'
                  : cancelling
                    ? 'Requesting cancellation...'
                    : 'Cancel operation'}
              </button>
            )}
          </div>
        )}
      {awaitingDispatch && !active && status !== 'verified' && (
        <p role="status" className="text-slate-400">
          Drive sync queued. Verification is still pending.
        </p>
      )}
      {(error || (!active && health.offsite_error)) && (
        <p role="alert" className="text-red-400 break-words">
          {error || health.offsite_error}
        </p>
      )}
      {health.offsite_location && (
        <div className="space-y-1">
          {driveFolderUrl && (
            <a
              href={driveFolderUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-300 underline underline-offset-2 hover:text-blue-200"
            >
              Open Drive files
            </a>
          )}
          <details className="text-slate-500">
            <summary className="cursor-pointer">Drive location</summary>
            <p className="mt-1 font-mono break-all">
              {health.offsite_location}
            </p>
          </details>
        </div>
      )}
      {health.latest_backup_id &&
        !active &&
        !awaitingDispatch &&
        status !== 'unconfigured' &&
        status !== 'verified' && (
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="inline-flex items-center gap-1.5 rounded bg-slate-700 px-3 py-1.5 text-slate-200 hover:bg-slate-600 disabled:opacity-50"
          >
            {syncing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CloudUpload className="h-3.5 w-3.5" />
            )}
            {syncing ? 'Queuing Drive sync...' : 'Sync saved backup to Drive'}
          </button>
        )}
    </section>
  )
}
