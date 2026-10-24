'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Plus } from 'lucide-react'
import { useRef, useState } from 'react'
import { BackupHistory } from '@/components/backup/BackupHistory'
import { useBackupHistoryRefresh } from '@/components/backup/backupPolling'
import { CollapsibleSection } from '@/components/backup/CollapsibleSection'
import { CreateBackupModal } from '@/components/backup/CreateBackupModal'
import { EncryptionSetup } from '@/components/backup/EncryptionSetup'
import { ExternalBackups } from '@/components/backup/ExternalBackups'
import { MachineBackupCard } from '@/components/backup/MachineBackupCard'
import { OffsiteCard } from '@/components/backup/OffsiteCard'
import { SourcesManager } from '@/components/backup/SourcesManager'
import { StorageSettings } from '@/components/backup/StorageSettings'
import { ProjectSnapshotsCard } from '@/components/snapshots/ProjectSnapshotsCard'
import {
  type Backup,
  fetchAllBackups,
  fetchBackupDestinations,
  fetchBackupHealth,
  fetchBackupSources,
  fetchNativeHostBackupStatus,
} from '@/lib/api/backups'
import { POLL_NOTIFICATIONS, STALE_GIT } from '@/lib/polling'

export function BackupsClient() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const dispatchedAtRef = useRef(0)

  const { data: sources = [] } = useQuery({
    queryKey: ['backup-sources'],
    queryFn: () => fetchBackupSources(),
  })

  const {
    data: backupsData,
    isLoading: backupsLoading,
    error: backupsError,
    refetch: refetchBackups,
  } = useQuery({
    queryKey: ['all-backups', statusFilter],
    queryFn: () =>
      fetchAllBackups({ limit: 100, status: statusFilter || undefined }),
    refetchInterval: (query) => {
      const backups = query.state.data?.backups
      if (!backups) return 10000
      const hasActive = backups.some(
        (b: Backup) => b.status === 'pending' || b.status === 'running',
      )
      return hasActive || Date.now() - dispatchedAtRef.current < 30_000
        ? 3000
        : false
    },
  })

  const {
    data: healthData,
    isLoading: healthLoading,
    error: healthError,
    refetch: refetchHealth,
  } = useQuery({
    queryKey: ['backup-health'],
    queryFn: fetchBackupHealth,
    refetchInterval: POLL_NOTIFICATIONS,
  })
  useBackupHistoryRefresh(healthData?.sources)

  const {
    data: destinations,
    isLoading: destinationsLoading,
    error: destinationsError,
    refetch: refetchDestinations,
  } = useQuery({
    queryKey: ['backup-destinations'],
    queryFn: fetchBackupDestinations,
    staleTime: STALE_GIT,
  })

  const {
    data: nativeHostStatus,
    isLoading: nativeHostLoading,
    error: nativeHostError,
    refetch: refetchNativeHost,
  } = useQuery({
    queryKey: ['native-host-backup'],
    queryFn: fetchNativeHostBackupStatus,
    staleTime: STALE_GIT,
  })

  const backups = backupsData?.backups ?? []
  const scheduledCount = sources.filter((source) => source.enabled).length

  const invalidateAll = async () => {
    dispatchedAtRef.current = Date.now()
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['all-backups'] }),
      queryClient.invalidateQueries({ queryKey: ['backup-health'] }),
      queryClient.invalidateQueries({ queryKey: ['backup-sources'] }),
    ])
  }

  const refreshSources = () => {
    queryClient.invalidateQueries({ queryKey: ['backup-sources'] })
    queryClient.invalidateQueries({ queryKey: ['backup-health'] })
  }

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-7xl mx-auto">
      {showCreateModal && (
        <CreateBackupModal
          sources={sources}
          onClose={() => setShowCreateModal(false)}
          onCreated={invalidateAll}
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-md bg-indigo-500/10 border border-indigo-500/20">
            <Archive className="w-5 h-5 text-indigo-400" />
          </div>
          <h1 className="text-2xl font-bold text-slate-100 display tracking-tight leading-none">
            Backups
          </h1>
        </div>
        <button
          type="button"
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 text-2xs px-3 py-1.5 rounded-md bg-phosphor-500/12 text-phosphor-400 border border-phosphor-500/20 hover:bg-phosphor-500/20 hover:border-phosphor-500/40 transition-all font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
          data-testid="backup-manual-trigger"
        >
          <Plus className="w-3.5 h-3.5" />
          Back up a source now
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ProjectSnapshotsCard />
        <MachineBackupCard
          status={nativeHostStatus}
          scheduleWindow={destinations?.schedule_window}
          isLoading={nativeHostLoading}
          error={nativeHostError}
          onRefresh={() => {
            void refetchNativeHost()
          }}
        />
        <OffsiteCard
          health={healthData}
          destinations={destinations}
          isLoading={healthLoading || destinationsLoading}
          error={healthError ?? destinationsError}
          onRefresh={() => {
            void refetchHealth()
            void refetchDestinations()
          }}
        />
      </div>

      <CollapsibleSection
        title="Sources"
        summary={
          sources.length === 0
            ? 'No sources set up yet.'
            : `${sources.length} sources copied offsite, ${scheduledCount} on a schedule`
        }
      >
        <SourcesManager
          sources={sources}
          healthItems={healthData?.sources ?? []}
          recentBackups={backups}
          onSourceChanged={refreshSources}
          onBackupTriggered={invalidateAll}
          showHeader={false}
        />
        <div className="mt-4">
          <ExternalBackups />
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Storage and recovery key"
        summary="Where offsite copies are kept, repository maintenance, and the key that unlocks them"
      >
        <div className="space-y-4">
          <StorageSettings proxmoxConfigured={destinations?.proxmox != null} />
          <EncryptionSetup />
        </div>
      </CollapsibleSection>

      <BackupHistory
        backups={backups}
        sources={sources}
        isLoading={backupsLoading}
        error={backupsError}
        onRetry={() => {
          void refetchBackups()
        }}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
      />
    </div>
  )
}
