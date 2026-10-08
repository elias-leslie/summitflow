import type { Backup } from '@/lib/api/backups'
import { formatBytes } from '@/lib/format'

function measuredBytes(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : null
}

export function BackupSizeDetails({
  backup,
}: {
  backup: Pick<Backup, 'size_bytes' | 'verification_json'>
}) {
  const verification = backup.verification_json
  const restic = verification?.format === 'restic-v1'
  const contents = restic
    ? (measuredBytes(verification.logical_bytes) ??
      measuredBytes(backup.size_bytes))
    : measuredBytes(backup.size_bytes)
  const added = restic ? measuredBytes(verification.stored_bytes) : null
  return (
    <div className="space-y-1 text-xs text-slate-300">
      <div>
        <span className="text-slate-400">
          {restic ? 'Contents' : 'Archive'}:{' '}
        </span>
        <span className="font-mono">
          {contents == null
            ? 'Unavailable'
            : contents === 0
              ? '0 B'
              : formatBytes(contents)}
        </span>
      </div>
      <div>
        <span className="text-slate-400">New storage: </span>
        <span className="font-mono">
          {added == null
            ? 'Not recorded'
            : added === 0
              ? '0 B'
              : formatBytes(added)}
        </span>
      </div>
    </div>
  )
}

export function BackupSizeExplanation() {
  return (
    <p className="text-xs text-slate-400">
      Contents is the full data in a backup. New storage is compressed data
      added after reusing unchanged data, before pruning. Older backups show
      archive size. These values are not total disk usage.
    </p>
  )
}
