import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import type {
  BackupActivity,
  BackupHealthItem,
  BackupListResponse,
} from '@/lib/api/backups'

type HistoryHealth = Pick<
  BackupHealthItem,
  'source_id' | 'latest_backup_id' | 'last_success_at' | 'offsite_status'
> & {
  backup_activity?: Pick<
    BackupActivity,
    'backup_id' | 'run_id' | 'active'
  > | null
}

export function useBackupHistoryRefresh(
  sources: readonly HistoryHealth[] | undefined,
) {
  const client = useQueryClient()
  const previous = useRef<string | null>(null)
  const revision =
    sources == null
      ? null
      : JSON.stringify(
          sources
            .map((source) => [
              source.source_id,
              source.latest_backup_id,
              source.last_success_at,
              source.offsite_status,
              source.backup_activity?.backup_id,
              source.backup_activity?.run_id,
              source.backup_activity?.active,
            ])
            .sort((left, right) =>
              String(left[0]).localeCompare(String(right[0])),
            ),
        )

  useEffect(() => {
    if (revision == null) return
    const changed = previous.current != null && previous.current !== revision
    previous.current = revision
    if (!changed) return
    // Reuse the existing health poll to notice work started by ST or schedules.
    // Phase/part updates do not trigger redundant history or storage requests.
    void client.invalidateQueries({ queryKey: ['all-backups'] })
    void client.invalidateQueries({ queryKey: ['storage-summary'] })
  }, [client, revision])
}

type BackupQuerySnapshot = {
  state: {
    data?: BackupListResponse
  }
}

export function activeBackupRefetchInterval(
  query: BackupQuerySnapshot,
  dispatchedAt: number,
) {
  const backups = query.state.data?.backups
  if (!backups) return 10000

  const hasActive = backups.some(
    (backup) => backup.status === 'pending' || backup.status === 'running',
  )
  const recentlyDispatched = Date.now() - dispatchedAt < 30_000
  return hasActive || recentlyDispatched ? 3000 : false
}
