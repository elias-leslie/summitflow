'use client'

import { CloudUpload, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { type BackupHealthItem, syncBackupOffsite } from '@/lib/api/backups'
import { formatDate } from '@/lib/format'

const LABELS = {
  verified: 'Verified encrypted copy',
  pending: 'Not yet verified',
  failed: 'Sync failed',
  unconfigured: 'Not configured',
} as const

export function OffsiteStatus({
  health,
  onSaved,
}: {
  health: BackupHealthItem
  onSaved: () => void
}) {
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState(false)
  const status = health.offsite_status ?? 'unconfigured'
  const handleSync = async () => {
    if (!health.latest_backup_id) return
    setSyncing(true)
    setError(null)
    try {
      const result = await syncBackupOffsite(
        health.source_id,
        health.latest_backup_id,
      )
      setQueued(result.status === 'queued')
      onSaved()
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : 'Could not sync this backup',
      )
    } finally {
      setSyncing(false)
    }
  }

  return (
    <section
      aria-label="Backup recovery copies"
      className="space-y-2 rounded border border-slate-700/50 bg-slate-950/40 p-3 text-xs"
    >
      <dl className="grid gap-2 sm:grid-cols-3">
        <div>
          <dt className="text-slate-500">Local backup</dt>
          <dd className="text-slate-200">
            {health.last_success_at
              ? formatDate(health.last_success_at)
              : 'No successful backup'}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Google Drive</dt>
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
      <p className="text-slate-400">
        One encrypted local archive, copied unchanged to Drive. Sync retries
        reuse that archive.
      </p>
      {queued && status !== 'verified' && (
        <p role="status" className="text-slate-400">
          Drive sync queued. Verification is still pending.
        </p>
      )}
      {(error || health.offsite_error) && (
        <p role="alert" className="text-red-400 break-words">
          {error || health.offsite_error}
        </p>
      )}
      {health.offsite_location && (
        <p className="font-mono text-slate-500 break-all">
          {health.offsite_location}
        </p>
      )}
      {health.latest_backup_id &&
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
            {syncing ? 'Syncing saved backup...' : 'Sync saved backup to Drive'}
          </button>
        )}
    </section>
  )
}
