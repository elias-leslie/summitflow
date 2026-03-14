'use client'

import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { RestoreConfirmation } from '@/components/backup/RestoreConfirmation'
import { fetchBackupSource, fetchSourceBackups } from '@/lib/api/backups'

export function SourceRestoreClient() {
  const params = useParams()
  const router = useRouter()
  const sourceId = params.sourceId as string
  const backupId = params.backupId as string

  const { data: source, isLoading: sourceLoading } = useQuery({
    queryKey: ['backup-source', sourceId],
    queryFn: () => fetchBackupSource(sourceId),
  })

  const { data: backupsData, isLoading: backupsLoading } = useQuery({
    queryKey: ['source-backups', sourceId],
    queryFn: () => fetchSourceBackups(sourceId, { limit: 200 }),
  })

  const backup = backupsData?.backups.find((b) => b.id === backupId)

  const handleClose = () => {
    router.push(`/backups/${sourceId}`)
  }

  const handleSuccess = () => {
    // Could trigger a notification or do other actions
  }

  if (sourceLoading || backupsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (!source || !backup) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">
          {!source ? 'Source not found' : 'Backup not found'}
        </p>
        <Link
          href={`/backups/${sourceId}`}
          className="text-blue-400 hover:text-blue-300"
        >
          Back to source
        </Link>
      </div>
    )
  }

  if (backup.status !== 'completed') {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">
          Cannot restore from a backup that is not completed.
        </p>
        <p className="text-sm text-slate-500">Backup status: {backup.status}</p>
        <Link
          href={`/backups/${sourceId}`}
          className="text-blue-400 hover:text-blue-300"
        >
          Back to source
        </Link>
      </div>
    )
  }

  return (
    <RestoreConfirmation
      backup={backup}
      sourceId={sourceId}
      projectName={source.name}
      onClose={handleClose}
      onSuccess={handleSuccess}
    />
  )
}
