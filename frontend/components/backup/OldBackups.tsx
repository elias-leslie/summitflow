import type { OldBackups as Legacy } from '@/lib/api/backups'
import { formatBytes } from '@/lib/format'
import { CollapsibleSection } from './CollapsibleSection'

function Row({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <li className="py-2">
      <p className="text-slate-200">{title}</p>
      <p className="mt-0.5 break-words text-slate-500">{children}</p>
    </li>
  )
}

/** What the retired backup shape left behind. Read-only: nothing here has a button. */
export function OldBackups({ legacy }: { legacy: Legacy }) {
  const repo = legacy.local_repository
  const drive = legacy.drive_snapshots
  const days = drive.ages_out_after_days
  return (
    <CollapsibleSection
      title="Old backups, ageing out"
      summary="Left from the earlier per-project backups. Nothing writes to them any more."
    >
      <ul
        className="divide-y divide-slate-800/60 text-xs"
        data-testid="old-backups"
      >
        <Row title="Old backup copy on the T7">
          {repo.path
            ? `${repo.path}${repo.bytes ? `, ${formatBytes(repo.bytes)}` : ''}. `
            : 'Size not measured yet. '}
          Nothing writes to it, so you can delete it.
        </Row>
        <Row title="Old copies on Google Drive">
          {drive.count === null
            ? 'Not counted yet. '
            : `${drive.count} ${drive.count === 1 ? 'copy' : 'copies'} left. `}
          They are removed on their own after {days} days.
        </Row>
        {legacy.retired_sources > 0 && (
          <Row title="Old per-project backups">
            {legacy.retired_sources} switched off. Projects are now backed up
            together in the local points and the Google Drive copy.
          </Row>
        )}
      </ul>
    </CollapsibleSection>
  )
}
