import { FilesWorkspace } from '@/components/files'

export default function GlobalFilesPage(): React.ReactElement {
  return (
    <FilesWorkspace
      scope={{ kind: 'workspace' }}
      title="Global Files"
      rootLabel="/"
      rootHref="/files"
      emptyTitle="Browse from filesystem root"
      emptyBody="Start at / and drill into any reachable folder level. Restricted directories can fail per-folder without blocking the rest of the explorer."
    />
  )
}
