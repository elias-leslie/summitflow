import { clsx } from 'clsx'
import { type DriveRow, relativeTime } from '@/lib/backup-overview'

/** One row per thing the daily copy reads: what it is, when Drive last got it, and how big. */
export function DriveJobs({ rows }: { rows: DriveRow[] }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs text-slate-500">What's in the copy</h3>
      <ul className="divide-y divide-slate-800/60 text-xs">
        {rows.map((row) => (
          <li key={row.key} className="py-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-slate-200">{row.label}</span>
              <span
                className={clsx(
                  'text-right tabular-nums',
                  row.failed
                    ? 'text-rose-300'
                    : row.has
                      ? 'text-slate-400'
                      : 'text-slate-500',
                )}
              >
                {row.failed
                  ? 'Not backed up'
                  : row.has
                    ? [relativeTime(row.when, ''), row.size]
                        .filter(Boolean)
                        .join(' · ')
                    : 'Not copied yet'}
              </span>
            </div>
            {row.note && (
              <p
                className={clsx(
                  'mt-0.5 break-words',
                  row.failed ? 'text-rose-300' : 'text-slate-500',
                )}
              >
                {row.note}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
