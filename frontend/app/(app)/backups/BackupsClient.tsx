'use client'

import { useQuery } from '@tanstack/react-query'
import { Archive } from 'lucide-react'
import { BackUpNow } from '@/components/backup/BackUpNow'
import { CollapsibleSection } from '@/components/backup/CollapsibleSection'
import { DriveCard } from '@/components/backup/DriveCard'
import { EncryptionSetup } from '@/components/backup/EncryptionSetup'
import { ExternalBackups } from '@/components/backup/ExternalBackups'
import { HealthBanner } from '@/components/backup/HealthBanner'
import { LocalPointsCard } from '@/components/backup/LocalPointsCard'
import { OldBackups } from '@/components/backup/OldBackups'
import {
  ProjectSnapshotsCard,
  ProjectSnapshotsList,
} from '@/components/snapshots/ProjectSnapshotsCard'
import { fetchBackupOverview } from '@/lib/api/backups'
import { isRunning } from '@/lib/backup-overview'
import { POLL_FAST, POLL_NOTIFICATIONS } from '@/lib/polling'

export function BackupsClient() {
  const {
    data: overview,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['backup-overview'],
    queryFn: fetchBackupOverview,
    refetchInterval: (query) => {
      const data = query.state.data
      const running =
        data?.offsite.running || isRunning(data?.local.last_run?.status)
      return running ? POLL_FAST : POLL_NOTIFICATIONS
    },
  })

  const running = !!overview?.offsite.running

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div className="flex items-center gap-3">
        <div className="rounded-md border border-indigo-500/20 bg-indigo-500/10 p-1.5">
          <Archive className="h-5 w-5 text-indigo-400" />
        </div>
        <h1 className="display text-2xl font-bold leading-none tracking-tight text-slate-100">
          Backups
        </h1>
      </div>

      {isLoading && (
        <div
          role="status"
          className="h-16 animate-pulse rounded-lg bg-slate-800/40"
        >
          <span className="sr-only">Loading backup status</span>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-700/60 bg-slate-900/40 px-4 py-3 text-sm"
        >
          <p className="text-slate-300">
            {overview
              ? `Couldn't refresh. Showing the last status. ${error.message}`
              : `Couldn't load backup status. ${error.message}`}
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
          >
            Try again
          </button>
        </div>
      )}

      {overview && (
        <>
          <HealthBanner overview={overview} />
          <div className="grid gap-4 lg:grid-cols-2">
            <LocalPointsCard overview={overview} />
            <DriveCard overview={overview} />
          </div>
          <BackUpNow running={running} />
        </>
      )}

      <ExternalBackups />

      <section aria-label="Project snapshots" className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <ProjectSnapshotsCard />
        </div>
        <ProjectSnapshotsList />
      </section>

      <CollapsibleSection
        title="Recovery key"
        summary="The key that unlocks older encrypted copies on Google Drive"
      >
        <EncryptionSetup />
      </CollapsibleSection>

      {overview && <OldBackups legacy={overview.legacy} />}
    </div>
  )
}
