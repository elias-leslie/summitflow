import type { BackupOverview } from '@/lib/api/backups'
import {
  isOk,
  isRunning,
  pointRows,
  relativeTime,
  spaceUsage,
} from '@/lib/backup-overview'
import type { BlockStatus, StatusFact } from '@/lib/backup-status'
import { DetailValue, StatusBlock } from './StatusBlock'

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function localStatus(overview: BackupOverview): BlockStatus {
  const { local, problems } = overview
  const run = local.last_run
  const missing = problems.some((problem) => problem.key === 'local-missing')
  const facts: StatusFact[] = [
    { label: 'Runs', value: capitalize(local.schedule) },
    { label: 'Kept', value: local.keeps },
  ]
  if (run) {
    const failed = !isOk(run.status) && !isRunning(run.status)
    facts.push({
      label: 'Last run',
      value: isRunning(run.status)
        ? 'Running now'
        : `${failed ? 'Failed ' : ''}${relativeTime(run.finished_at ?? run.started_at, 'time not recorded')}`,
      tone: failed ? 'warn' : undefined,
    })
  } else {
    facts.push({ label: 'Last run', value: 'None yet' })
  }
  facts.push({
    label: 'Next run',
    value: relativeTime(local.next_run_at, 'Not available'),
  })

  if (!local.enabled)
    return {
      tone: 'unknown',
      headline: 'Local backups are switched off',
      facts,
    }
  if (!local.last_good_at)
    return {
      tone: missing ? 'bad' : 'unknown',
      headline: 'No local point yet',
      facts,
    }
  return {
    tone: missing ? 'bad' : 'ok',
    headline: `Newest point ${relativeTime(local.last_good_at, 'time not recorded')}`,
    facts,
  }
}

export function LocalPointsCard({ overview }: { overview: BackupOverview }) {
  const { local } = overview
  const status = localStatus(overview)
  const points = pointRows(local.points)
  const space = local.target ? spaceUsage(local.target) : null
  const lastError = local.last_run?.error

  return (
    <StatusBlock
      title="Local backup points"
      subtitle="Snapshots of this machine on the T7 drive"
      status={status}
      toneLabel={status.tone === 'unknown' ? 'Waiting' : undefined}
      testId="local-points-card"
      details={
        <dl className="space-y-2">
          {local.retention && (
            <DetailValue label="How points are kept" value={local.retention} />
          )}
          {local.target && (
            <DetailValue label="Drive path" value={local.target.path} mono />
          )}
        </dl>
      }
    >
      {lastError && !isOk(local.last_run?.status) && (
        <p className="text-xs text-amber-300">{lastError}</p>
      )}
      {space && (
        <div data-testid="local-space">
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="text-slate-200">{space.free} free</span>
            <span className="text-slate-500">
              {space.used} used of {space.total}
            </span>
          </div>
          <div
            role="img"
            aria-label={`${space.usedPercent}% of the backup drive is used`}
            className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800"
          >
            <div
              className="h-full rounded-full bg-slate-400"
              style={{ width: `${space.usedPercent}%` }}
            />
          </div>
        </div>
      )}
      <div>
        <h3 className="mb-1.5 text-xs text-slate-500">Points per folder</h3>
        {points.length > 0 ? (
          <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            {points.map((point) => (
              <li key={point.name} className="flex justify-between gap-2">
                <span className="text-slate-300">{point.label}</span>
                <span className="tabular-nums text-slate-400">
                  {point.count}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-500">
            The drive's points can't be counted right now.
          </p>
        )}
      </div>
    </StatusBlock>
  )
}
