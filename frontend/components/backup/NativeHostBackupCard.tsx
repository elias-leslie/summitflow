'use client'

import { clsx } from 'clsx'
import type { NativeHostBackupStatus } from '@/lib/api/backups-infra'
import { formatBytes, formatDate } from '@/lib/format'

interface NativeHostBackupCardProps {
  status: NativeHostBackupStatus | undefined
  isLoading: boolean
  error?: Error | null
  onRefresh: () => void
}

function readiness(
  status: NativeHostBackupStatus | undefined,
  isLoading: boolean,
) {
  if (isLoading) return 'Loading'
  if (!status) return 'Unavailable'
  if (!status.installed) return 'Not installed'
  if (!status.configured) return 'Setup pending'
  if (!status.enabled) return 'Disabled'
  return status.ready ? 'Ready to capture' : 'Blocked'
}

function bytes(value: number | undefined) {
  return value === undefined
    ? 'Unavailable'
    : value === 0
      ? '0 B'
      : formatBytes(value)
}

function blockerReason(value: string) {
  return value === 'insufficient-host-policy-headroom'
    ? 'Source or destination free space is below the capture budget and reserve.'
    : value
}

export function NativeHostBackupCard({
  status,
  isLoading,
  error,
  onRefresh,
}: NativeHostBackupCardProps) {
  const label = readiness(status, isLoading)
  const latest = status?.last_result
  const capacity = status?.capacity
  return (
    <details className="rounded-lg border border-slate-700/60 bg-slate-900/30 overflow-hidden">
      <summary className="cursor-pointer px-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
        <span className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300 display">
          Native Linux Recovery
        </span>
        <span
          className={clsx(
            'ml-3 text-xs',
            label === 'Blocked' ? 'text-amber-300' : 'text-slate-300',
          )}
        >
          {label}
        </span>
        <span className="mt-1 block text-xs text-slate-400">
          {isLoading
            ? 'Loading native host backup status…'
            : !status
              ? 'Native Linux backup status unavailable'
              : status.blocked_reason
                ? blockerReason(status.blocked_reason)
                : `${status.engine}; ${status.retention}. ${latest ? `Latest capture: ${latest.status.replaceAll('_', ' ')}.` : 'No capture recorded.'}`}
        </span>
      </summary>
      <div className="border-t border-slate-800/40 px-4 py-4 space-y-3">
        {error && (
          <p role="alert" className="text-xs text-rose-300">
            {status ? 'Refresh failed; showing last loaded status. ' : ''}
            {error.message}
          </p>
        )}
        {isLoading && (
          <p role="status" className="text-xs text-slate-400">
            Loading native host backup status…
          </p>
        )}
        {status && (
          <>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-xs">
              <StatusValue
                label="Engine"
                value={`${status.engine}: ${status.installed ? 'installed' : 'not installed'}`}
              />
              <StatusValue
                label="Configuration"
                value={
                  status.configured ? 'Configured' : 'Pending storage cutover'
                }
              />
              <StatusValue
                label="Capture"
                value={status.enabled ? label : 'Disabled'}
              />
              <StatusValue label="Retention" value={status.retention} />
              <StatusValue
                label="Destination"
                value={status.target ?? 'Not configured'}
                mono
              />
              <StatusValue
                label="Latest capture"
                value={
                  latest?.status.replaceAll('_', ' ') ?? 'No capture recorded'
                }
              />
            </dl>
            {status.sources && status.sources.length > 0 && (
              <div className="text-xs">
                <span className="text-slate-400">Source subvolumes</span>
                <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-slate-200">
                  {status.sources.map((source) => (
                    <li className="break-all" key={source}>
                      {source}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {capacity ? (
              <>
                <p
                  className={clsx(
                    'text-xs',
                    capacity.admitted ? 'text-slate-300' : 'text-amber-300',
                  )}
                >
                  {capacity.admitted
                    ? 'Capture headroom available'
                    : 'Insufficient capture headroom'}
                  {capacity.under_pressure
                    ? '; destination under pressure'
                    : ''}
                </p>
                <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                  <StatusValue
                    label="Destination free"
                    value={bytes(capacity.free_bytes)}
                  />
                  <StatusValue
                    label="Destination used"
                    value={bytes(capacity.used_bytes)}
                  />
                  <StatusValue
                    label="Full-capture budget"
                    value={bytes(capacity.expected_growth_bytes)}
                  />
                  <StatusValue
                    label="Required reserve"
                    value={bytes(capacity.reserve_bytes)}
                  />
                </dl>
                <p className="text-xs text-slate-400">
                  Capacity currently reserves room for a full capture.
                  Incremental capacity needs qualification on the final
                  destination.
                </p>
                {capacity.reason &&
                  capacity.reason !== status.blocked_reason && (
                    <p className="text-xs text-amber-300">
                      {blockerReason(capacity.reason)}
                    </p>
                  )}
                {capacity.source_filesystems.some(
                  (source) => source.under_pressure,
                ) && (
                  <p className="text-xs text-amber-300">
                    Source filesystem under pressure:{' '}
                    {capacity.source_filesystems
                      .filter((source) => source.under_pressure)
                      .map((source) => source.path)
                      .join(', ')}
                  </p>
                )}
              </>
            ) : (
              <p className="text-xs text-slate-400">Capacity not reported.</p>
            )}
            {latest && (
              <dl className="grid gap-3 sm:grid-cols-2 text-xs">
                <StatusValue
                  label="Started"
                  value={
                    latest.started_at
                      ? formatDate(latest.started_at)
                      : 'Unavailable'
                  }
                />
                <StatusValue
                  label="Finished"
                  value={
                    latest.finished_at
                      ? formatDate(latest.finished_at)
                      : 'Not recorded'
                  }
                />
                <StatusValue
                  label="Remaining capacity"
                  value={bytes(latest.remaining_capacity_bytes)}
                />
                <StatusValue
                  label="Reclaimed"
                  value={bytes(latest.reclaimed_bytes)}
                />
                {latest.evidence && (
                  <StatusValue
                    label="Capture evidence"
                    value={latest.evidence}
                    mono
                  />
                )}
                {latest.boot_path && (
                  <StatusValue
                    label="Boot recovery location"
                    value={latest.boot_path}
                    mono
                  />
                )}
              </dl>
            )}
            {latest?.error && (
              <p role="alert" className="break-words text-xs text-rose-300">
                {latest.error}
              </p>
            )}
          </>
        )}
        <p className="text-xs text-slate-400">
          Windows recovery uses the Veeam agent in Windows. Linux status does
          not verify Windows backups.
        </p>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="btn-secondary text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
        >
          Refresh native Linux status
        </button>
      </div>
    </details>
  )
}

function StatusValue({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-slate-400">{label}</dt>
      <dd
        className={clsx(
          'break-words text-slate-200',
          mono && 'break-all font-mono',
        )}
      >
        {value}
      </dd>
    </div>
  )
}
