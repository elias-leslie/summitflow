'use client'

import { useMemo } from 'react'
import type { NativeHostBackupStatus } from '@/lib/api/backups-infra'
import { machineBackupStatus } from '@/lib/backup-status'
import { formatBytes, formatDate } from '@/lib/format'
import { DetailValue, StatusBlock } from './StatusBlock'

interface MachineBackupCardProps {
  status: NativeHostBackupStatus | undefined
  scheduleWindow: string | null | undefined
  isLoading: boolean
  error?: Error | null
  onRefresh: () => void
}

function bytes(value: number | undefined) {
  if (value === undefined) return 'Not reported'
  return value === 0 ? '0 B' : formatBytes(value)
}

function blockerText(value: string) {
  return value === 'insufficient-host-policy-headroom'
    ? 'Not enough free space on the source or the T7 for the next backup.'
    : value
}

/** Nightly btrbk backup of the whole Linux machine to the T7. */
export function MachineBackupCard({
  status,
  scheduleWindow,
  isLoading,
  error,
  onRefresh,
}: MachineBackupCardProps) {
  const block = useMemo(
    () => machineBackupStatus(status, scheduleWindow),
    [status, scheduleWindow],
  )
  const latest = status?.last_result
  const capacity = status?.capacity
  const underPressure =
    capacity?.source_filesystems
      .filter((source) => source.under_pressure)
      .map((source) => source.path) ?? []

  return (
    <StatusBlock
      title="Machine backup"
      subtitle="Whole Linux machine to the T7 drive, every night (btrbk)"
      status={block}
      isLoading={isLoading}
      error={error}
      testId="machine-backup"
      details={
        status ? (
          <>
            {status.blocked_reason && (
              <p className="text-amber-300">
                {blockerText(status.blocked_reason)}
              </p>
            )}
            {latest?.error && (
              <p role="alert" className="break-words text-rose-300">
                {latest.error}
              </p>
            )}
            {status.restore_test_error && (
              <p className="break-words text-rose-300">
                Restore test: {status.restore_test_error}
              </p>
            )}
            <dl className="grid gap-3 sm:grid-cols-2">
              <DetailValue
                label="Latest run"
                value={
                  latest
                    ? `${latest.status.replaceAll('_', ' ')}${latest.started_at ? `, ${formatDate(latest.started_at)}` : ''}`
                    : 'None recorded'
                }
              />
              <DetailValue
                label="Free on the T7"
                value={`${bytes(capacity?.free_bytes)}${capacity ? ` (keeps ${bytes(capacity.reserve_bytes)} spare)` : ''}`}
              />
              <DetailValue
                label="Destination"
                value={status.target ?? 'Not configured'}
                mono
              />
              {latest?.boot_path && (
                <DetailValue label="Boot files" value={latest.boot_path} mono />
              )}
              {latest?.evidence && (
                <DetailValue label="Run log" value={latest.evidence} mono />
              )}
            </dl>
            {status.sources && status.sources.length > 0 && (
              <div>
                <p className="text-slate-500">Backed up</p>
                <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-slate-200">
                  {status.sources.map((source) => (
                    <li className="break-all" key={source}>
                      {source}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {underPressure.length > 0 && (
              <p className="text-amber-300">
                Low on space: {underPressure.join(', ')}
              </p>
            )}
            <button
              type="button"
              onClick={onRefresh}
              disabled={isLoading}
              className="btn-secondary text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
            >
              Refresh
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="btn-secondary text-xs"
          >
            Retry
          </button>
        )
      }
    />
  )
}
