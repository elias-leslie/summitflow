'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { fetchSnapshots } from '@/lib/api/snapshots'
import { formatTimeAgo } from '@/lib/format'
import { STALE_GIT } from '@/lib/polling'

export function SavedWorkEvidence({ projectId }: { projectId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['saved-work-evidence', projectId],
    queryFn: () => fetchSnapshots(projectId),
    staleTime: STALE_GIT,
  })
  const newest = data?.reduce<string | null>(
    (latest, snapshot) =>
      !latest || snapshot.created_at > latest ? snapshot.created_at : latest,
    null,
  )

  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-xs font-medium text-slate-300">
        Saved workspace edits
      </dt>
      <dd className="text-sm text-slate-100">
        {isLoading
          ? 'Loading Btrfs captures…'
          : data
            ? `${data.length} Btrfs saved-work ${data.length === 1 ? 'snapshot' : 'snapshots'}`
            : 'Unavailable'}
      </dd>
      {error && (
        <dd className="text-xs text-rose-300">
          {data ? 'Refresh failed; showing last loaded captures. ' : ''}
          {error.message}
        </dd>
      )}
      {newest && (
        <dd className="text-xs text-slate-400">
          Latest capture {formatTimeAgo(newest)}
        </dd>
      )}
      {data?.length === 0 && (
        <dd className="text-xs text-slate-400">
          No saved-work capture recorded
        </dd>
      )}
      <dd className="text-xs text-slate-400">
        Local workspace protection; offsite backup evidence is separate.
      </dd>
      <dd>
        <Link
          href="/backups"
          className="text-xs text-phosphor-300 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
        >
          Inspect saved-work recovery
        </Link>
      </dd>
    </div>
  )
}
