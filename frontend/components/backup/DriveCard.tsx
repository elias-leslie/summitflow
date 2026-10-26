import type { BackupOverview } from '@/lib/api/backups'
import { driveRows, isOk, isRunning, relativeTime } from '@/lib/backup-overview'
import type { BlockStatus, StatusFact, Tone } from '@/lib/backup-status'
import { DriveJobs } from './DriveJobs'
import { DetailValue, StatusBlock } from './StatusBlock'

function checkFact(drive: BackupOverview['offsite']): StatusFact {
  const check = drive.check
  if (
    !check ||
    (!check.last_ok_at && !check.error && check.status !== 'partial')
  )
    return { label: 'Data check', value: 'Runs weekly' }
  const sample = check.sample
    ? `, ${check.sample.replace(/M$/, ' MB')} read`
    : ''
  if (check.status === 'partial')
    return {
      label: 'Data check',
      value: `Out of time ${relativeTime(check.checked_at, 'earlier')}; reads a new sample next week`,
    }
  const failing = !isOk(check.status)
  return failing
    ? {
        label: 'Data check',
        value: `Failed ${check.failures > 1 ? `${check.failures} times in a row` : 'last time'}${check.error ? `: ${check.error}` : ''}`,
        tone: check.failures >= 2 ? 'bad' : 'warn',
      }
    : {
        label: 'Data check',
        value: `Passed ${relativeTime(check.last_ok_at, 'earlier')}${sample}`,
      }
}

function restoreFact(drive: BackupOverview['offsite']): StatusFact {
  const spot = drive.spot_restore
  if (!spot?.at) return { label: 'Test restore', value: 'Runs weekly' }
  if (spot.status === 'partial')
    return {
      label: 'Test restore',
      value: `Out of time ${relativeTime(spot.at, 'earlier')}; tries again next week`,
    }
  return isOk(spot.status)
    ? {
        label: 'Test restore',
        value: `Passed ${relativeTime(spot.at, 'earlier')}`,
      }
    : {
        label: 'Test restore',
        value: `Failed ${relativeTime(spot.at, 'earlier')}${spot.error ? `: ${spot.error}` : ''}`,
        tone: 'bad',
      }
}

function cleanupFact(drive: BackupOverview['offsite']): StatusFact {
  const upkeep = drive.maintenance
  const when = upkeep?.pruned_at ?? upkeep?.ran_at
  if (!when) return { label: 'Cleanup', value: 'Runs weekly' }
  return {
    label: 'Cleanup',
    value: `Done ${relativeTime(when, 'earlier')}`,
    tone: upkeep?.prune_error ? 'warn' : undefined,
  }
}

export function driveStatus(overview: BackupOverview): BlockStatus {
  const drive = overview.offsite
  const broken = overview.problems.some((problem) =>
    problem.key.startsWith('offsite-'),
  )
  const facts = [
    {
      label: 'Runs',
      value: drive.schedule === 'daily' ? 'Daily' : drive.schedule,
    },
    checkFact(drive),
    restoreFact(drive),
    cleanupFact(drive),
  ]
  let tone: Tone = broken ? 'bad' : 'ok'
  let headline: string
  if (drive.running)
    headline = `Copying now, started ${relativeTime(drive.running.started_at, 'just now')}`
  else if (drive.last_success_at)
    headline = `Last good copy ${relativeTime(drive.last_success_at, 'time not recorded')}`
  else {
    headline = 'First copy not made yet'
    if (!broken) tone = 'unknown'
  }
  if (isRunning(drive.status) && !drive.running) headline = 'Copying now'
  return { tone, headline, facts }
}

export function DriveCard({ overview }: { overview: BackupOverview }) {
  const drive = overview.offsite
  const status = driveStatus(overview)
  const failedRun =
    drive.status && !isOk(drive.status) && !isRunning(drive.status)
  const recent = [...drive.runs].reverse().slice(0, 7)

  return (
    <StatusBlock
      title="Google Drive copy"
      subtitle="One daily copy of the local points, plus database dumps"
      status={status}
      toneLabel={status.tone === 'unknown' ? 'Waiting' : undefined}
      testId="drive-card"
      detailsLabel={recent.length > 0 ? 'Recent daily runs' : undefined}
      details={
        recent.length > 0 && (
          <ul className="space-y-1">
            {recent.map((run) => (
              <li
                key={run.started_at ?? run.finished_at}
                className="flex justify-between gap-3"
              >
                <span className="text-slate-400">
                  {relativeTime(run.started_at, 'time not recorded')}
                </span>
                <span
                  className={
                    isOk(run.status) ? 'text-slate-300' : 'text-rose-300'
                  }
                >
                  {isOk(run.status) ? 'Good' : (run.error ?? 'Failed')}
                </span>
              </li>
            ))}
          </ul>
        )
      }
    >
      {failedRun && drive.error && (
        <p className="break-words text-xs text-amber-300">
          Last run: {drive.error}
        </p>
      )}
      <DriveJobs rows={driveRows(drive.jobs)} />
      {drive.repository && (
        <dl className="text-xs">
          <DetailValue label="Repository" value={drive.repository} mono />
        </dl>
      )}
    </StatusBlock>
  )
}
