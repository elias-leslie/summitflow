'use client'

import { useParams } from 'next/navigation'
import { FilesWorkspace } from '@/components/files'

export function FilesClient(): React.ReactElement {
  const params = useParams<{ id: string }>()

  return (
    <FilesWorkspace
      scope={{ kind: 'project', projectId: params.id }}
      title="Files"
      rootLabel={params.id}
      rootHref={`/projects/${params.id}/files`}
      emptyTitle="Browse project files"
      emptyBody="Select a file or directory from the tree to inspect it, upload new files, or download existing ones."
    />
  )
}
