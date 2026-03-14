'use client'

import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { RestoreConfirmation } from '@/components/backup/RestoreConfirmation'
import { fetchProject } from '@/lib/api'
import { fetchBackup } from '@/lib/api/backups'

export function RestoreClient() {
  const params = useParams()
  const router = useRouter()
  const projectId = params.id as string
  const backupId = params.backupId as string

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  const { data: backup, isLoading: backupLoading } = useQuery({
    queryKey: ['backup', projectId, backupId],
    queryFn: () => fetchBackup(projectId, backupId),
  })

  const handleClose = () => {
    router.push(`/projects/${projectId}/backups`)
  }

  const handleSuccess = () => {
    // Could trigger a notification or do other actions
  }

  if (projectLoading || backupLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (!project || !backup) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">
          {!project ? 'Project not found' : 'Backup not found'}
        </p>
        <Link
          href={`/projects/${projectId}/backups`}
          className="text-blue-400 hover:text-blue-300"
        >
          Back to backups
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
          href={`/projects/${projectId}/backups`}
          className="text-blue-400 hover:text-blue-300"
        >
          Back to backups
        </Link>
      </div>
    )
  }

  return (
    <RestoreConfirmation
      backup={backup}
      projectId={projectId}
      projectName={project.name}
      onClose={handleClose}
      onSuccess={handleSuccess}
    />
  )
}
