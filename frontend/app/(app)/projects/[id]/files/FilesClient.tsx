'use client'

import { useParams, useSearchParams } from 'next/navigation'
import { FilesWorkspace } from '@/components/files'

export function FilesClient(): React.ReactElement {
  const params = useParams<{ id: string }>()
  const searchParams = useSearchParams()
  const directoryPath = searchParams.has('directory')
    ? searchParams.get('directory') || ''
    : undefined
  const filePath =
    directoryPath === undefined
      ? searchParams.get('path') || undefined
      : undefined

  return (
    <FilesWorkspace
      key={
        directoryPath === undefined
          ? `file:${filePath || ''}`
          : `directory:${directoryPath}`
      }
      initialFilePath={filePath}
      initialDirectoryPath={directoryPath}
      scope={{ kind: 'project', projectId: params.id }}
      title="Files"
      rootLabel={params.id}
      rootHref={`/projects/${params.id}/files`}
      emptyTitle="Browse project files"
      emptyBody="Select a file or directory from the tree to inspect it, upload new files, or download existing ones."
    />
  )
}
