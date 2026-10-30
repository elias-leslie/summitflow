import { FilesWorkspace } from '@/components/files'

export default function GlobalFilesPage(): React.ReactElement {
  return (
    <FilesWorkspace
      scope={{ kind: 'workspace' }}
      title="Global Files"
      rootLabel="/"
      rootHref="/files"
      emptyTitle="Pick a file or folder"
      emptyBody="Global Files covers the workspaces folder shown above the tree. A folder you can't read shows its own error; the rest still works."
    />
  )
}
