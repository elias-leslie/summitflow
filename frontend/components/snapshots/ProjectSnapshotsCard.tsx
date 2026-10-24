'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, Loader2, Scissors } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CollapsibleSection } from '@/components/backup/CollapsibleSection'
import { DetailValue, StatusBlock } from '@/components/backup/StatusBlock'
import {
  createSnapshot,
  fetchScopes,
  fetchSnapshotSummary,
  fetchSnapshots,
  pruneSnapshots,
} from '@/lib/api/snapshots'
import { projectSnapshotsStatus } from '@/lib/backup-status'
import { formatBytes } from '@/lib/format'
import { STALE_GIT } from '@/lib/polling'
import { ScopeList } from './ScopeList'

/** Btrfs snapshots of /srv/workspaces, taken every few minutes, for undo. */
export function ProjectSnapshotsCard() {
  const queryClient = useQueryClient()
  const summaryQuery = useQuery({
    queryKey: ['snapshot-summary'],
    queryFn: () => fetchSnapshotSummary(),
    staleTime: STALE_GIT,
  })
  const scopesQuery = useQuery({
    queryKey: ['snapshot-scopes'],
    queryFn: () => fetchScopes(undefined, true),
    staleTime: STALE_GIT,
  })
  const pointsQuery = useQuery({
    queryKey: ['snapshot-points'],
    queryFn: () => fetchSnapshots(),
    staleTime: STALE_GIT,
    select: (snapshots) => snapshots.map((snapshot) => snapshot.created_at),
  })
  const scopes = scopesQuery.data ?? []
  const summary = summaryQuery.data
  const status = useMemo(
    () => projectSnapshotsStatus(summary, scopes, pointsQuery.data),
    [summary, scopes, pointsQuery.data],
  )

  const [busy, setBusy] = useState<'snap' | 'prune' | null>(null)
  const [feedback, setFeedback] = useState<{
    text: string
    failed: boolean
  } | null>(null)

  const refresh = () => {
    for (const key of [
      'snapshot-summary',
      'snapshot-scopes',
      'snapshot-points',
      'snapshot-scope',
      'saved-work-evidence',
    ])
      void queryClient.invalidateQueries({ queryKey: [key] })
  }

  const run = async (action: 'snap' | 'prune') => {
    setBusy(action)
    setFeedback(null)
    try {
      if (action === 'snap') {
        const snap = await createSnapshot('summitflow')
        setFeedback({
          text: `Snapshot ${snap.name ?? snap.id.slice(0, 16)} taken`,
          failed: false,
        })
      } else {
        const result = await pruneSnapshots(false)
        setFeedback({
          text: result.ok
            ? `Pruned ${result.pruned} snapshot${result.pruned === 1 ? '' : 's'}`
            : `${Number.isFinite(result.pruned) ? `${result.pruned} pruned; ` : ''}${result.error ?? 'Prune failed'}`,
          failed: !result.ok,
        })
      }
      refresh()
    } catch (error) {
      setFeedback({
        text:
          error instanceof Error
            ? error.message
            : action === 'snap'
              ? 'Snapshot failed'
              : 'Prune failed',
        failed: true,
      })
    }
    setBusy(null)
  }

  const policy = summary?.policy

  return (
    <StatusBlock
      title="Project snapshots"
      subtitle="Local Btrfs snapshots of /srv/workspaces for quick undo"
      status={status}
      isLoading={summaryQuery.isLoading}
      error={summaryQuery.error ?? scopesQuery.error}
      testId="project-snapshots"
      detailsLabel="Space used and retention"
      details={
        <>
          {summary && (
            <dl>
              <DetailValue
                label="Space used"
                value={
                  summary.total_usage_bytes === null
                    ? 'Not measured'
                    : summary.total_usage_bytes === 0
                      ? '0 B'
                      : formatBytes(summary.total_usage_bytes)
                }
              />
            </dl>
          )}
          {policy && (
            <p className="text-slate-400">
              Keeps every snapshot for {policy.recent_hours} h, one an hour to{' '}
              {policy.hourly_hours} h, then one a day for {policy.daily_days}{' '}
              days. Retired projects keep their newest snapshot for{' '}
              {policy.archived_keep_days} days. When the disk is low, only the
              newest {policy.pressure_keep_points} are kept.
            </p>
          )}
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void run('snap')}
          disabled={busy !== null}
          className="flex items-center gap-1.5 rounded bg-phosphor-500/10 px-2.5 py-1 text-2xs text-phosphor-400 transition-colors hover:bg-phosphor-500/20 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
        >
          {busy === 'snap' ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Camera className="h-3 w-3" />
          )}
          Take snapshot now
        </button>
        <button
          type="button"
          onClick={() => void run('prune')}
          disabled={busy !== null}
          className="flex items-center gap-1.5 rounded bg-slate-700/40 px-2.5 py-1 text-2xs text-slate-400 transition-colors hover:bg-slate-700/60 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
        >
          {busy === 'prune' ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Scissors className="h-3 w-3" />
          )}
          Prune now
        </button>
        {feedback && (
          <span
            role={feedback.failed ? 'alert' : 'status'}
            className={
              feedback.failed
                ? 'text-2xs text-rose-300'
                : 'text-2xs text-emerald-300'
            }
          >
            {feedback.text}
          </span>
        )}
      </div>
    </StatusBlock>
  )
}

/** Per-project snapshot list: browse points and recover saved work. */
export function ProjectSnapshotsList() {
  const scopesQuery = useQuery({
    queryKey: ['snapshot-scopes'],
    queryFn: () => fetchScopes(undefined, true),
    staleTime: STALE_GIT,
  })
  const scopes = scopesQuery.data ?? []
  const active = scopes.filter((scope) => scope.scope_state === 'active')
  const archived = scopes.filter((scope) => scope.scope_state === 'archived')
  return (
    <CollapsibleSection
      title="Project snapshot list"
      summary={
        scopesQuery.isLoading
          ? 'Loading projects…'
          : scopesQuery.error
            ? `Projects unavailable: ${scopesQuery.error.message}`
            : `${active.length} projects, ${archived.length} retired; open one to browse or recover saved work`
      }
    >
      <div className="space-y-3">
        <ScopeList scopes={active} />
        {archived.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs text-slate-500">Retired projects</p>
            <ScopeList scopes={archived} />
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}
