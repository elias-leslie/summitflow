'use client'

import { clsx } from 'clsx'
import { ArrowRight } from 'lucide-react'
import Link from 'next/link'
import { useMemo } from 'react'
import type {
  BackupDestinations,
  BackupHealthResponse,
} from '@/lib/api/backups'
import { offsiteStatus, TONE_TEXT } from '@/lib/backup-status'
import { formatTimeAgo } from '@/lib/format'
import { StatusBlock } from './StatusBlock'
import { WeeklyRestoreStatus } from './WeeklyRestoreStatus'

interface OffsiteCardProps {
  health: BackupHealthResponse | undefined
  destinations: BackupDestinations | undefined
  isLoading: boolean
  error?: Error | null
  onRefresh: () => void
}

/** restic sources, copied T7 → Google Drive → Proxmox. */
export function OffsiteCard({
  health,
  destinations,
  isLoading,
  error,
  onRefresh,
}: OffsiteCardProps) {
  const status = useMemo(
    () => offsiteStatus(health, destinations),
    [health, destinations],
  )
  return (
    <StatusBlock
      title="Offsite copies"
      subtitle="Project, config and database sources, encrypted with restic"
      status={status}
      isLoading={isLoading}
      error={error}
      testId="offsite-copies"
      detailsLabel="Weekly restore test"
      details={
        <WeeklyRestoreStatus
          health={health}
          isLoading={isLoading}
          error={null}
          onRefresh={onRefresh}
        />
      }
    >
      {status.destinations.length > 0 && (
        <ol aria-label="Copies in order" className="space-y-1.5 text-xs">
          {status.destinations.map((destination, index) => (
            <li
              key={destination.id}
              className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
            >
              <span className="flex min-w-[7.5rem] items-center gap-1.5 font-medium text-slate-200">
                {index > 0 && (
                  <ArrowRight
                    aria-hidden
                    className="h-3 w-3 shrink-0 text-slate-600"
                  />
                )}
                {destination.label}
              </span>
              <span
                className={
                  destination.tone === 'ok'
                    ? 'text-slate-400'
                    : TONE_TEXT[destination.tone]
                }
              >
                copy {formatTimeAgo(destination.lastCopyAt, 'never')}
                {' · '}
                checked {formatTimeAgo(destination.checkedAt, 'never')}
              </span>
              {destination.note && (
                <span
                  className={clsx(
                    'basis-full break-words pl-[1.125rem] text-2xs',
                    TONE_TEXT[destination.tone],
                  )}
                >
                  {destination.note}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      {status.failing.length > 0 && (
        <div className="text-xs">
          <p className="text-rose-300">Failing:</p>
          <ul className="mt-0.5 flex flex-wrap gap-x-3 gap-y-1">
            {status.failing.map((source) => (
              <li key={source.id}>
                <Link
                  href={`/backups/${encodeURIComponent(source.id)}`}
                  className="text-rose-200 underline underline-offset-2 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
                >
                  {source.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </StatusBlock>
  )
}
