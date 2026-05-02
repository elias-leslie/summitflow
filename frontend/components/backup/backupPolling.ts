import type { BackupListResponse } from '@/lib/api/backups'

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
