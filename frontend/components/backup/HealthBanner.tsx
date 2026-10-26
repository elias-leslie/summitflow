import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { BackupOverview } from '@/lib/api/backups'

/** Calm when every recovery point is current; the problems themselves when one is really missing. */
export function HealthBanner({ overview }: { overview: BackupOverview }) {
  if (overview.problems.length > 0)
    return (
      <section
        aria-label="Backup problems"
        data-testid="backup-banner"
        data-tone="bad"
        className="rounded-lg border border-rose-500/30 bg-rose-500/8 px-4 py-3"
      >
        <div className="flex items-center gap-2 text-rose-200">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
          <h2 className="display text-sm font-semibold">
            {overview.problems.length === 1
              ? 'A backup needs attention'
              : `${overview.problems.length} backups need attention`}
          </h2>
        </div>
        <ul className="mt-2 space-y-2">
          {overview.problems.map((problem) => (
            <li key={problem.key} className="text-sm">
              <p className="font-medium text-slate-100">{problem.title}</p>
              <p className="break-words text-xs text-slate-300">
                {problem.message}
              </p>
            </li>
          ))}
        </ul>
      </section>
    )

  const driveStarted = overview.offsite.last_success_at !== null
  return (
    <section
      aria-label="Backup health"
      data-testid="backup-banner"
      data-tone={driveStarted ? 'ok' : 'unknown'}
      className="flex items-start gap-2 rounded-lg border border-slate-700/60 bg-slate-900/40 px-4 py-3"
    >
      <CheckCircle2
        className={`mt-0.5 h-4 w-4 shrink-0 ${driveStarted ? 'text-emerald-300' : 'text-slate-400'}`}
        aria-hidden
      />
      <div>
        <h2 className="display text-sm font-semibold text-slate-100">
          {driveStarted ? 'All backups current' : 'Nothing is missing'}
        </h2>
        <p className="text-xs text-slate-400">
          {driveStarted
            ? 'Local points are taken every 4 hours and copied to Google Drive daily. Nothing needs you.'
            : 'The first Google Drive copy runs with the next daily run. Nothing needs you.'}
        </p>
      </div>
    </section>
  )
}
