import { NotesPanel, NotesProvider } from '@summitflow/notes-ui'

interface NotesPopoutPageProps {
  searchParams?:
    | Promise<Record<string, string | string[] | undefined>>
    | Record<string, string | string[] | undefined>
}

export default async function NotesPopoutPage({
  searchParams,
}: NotesPopoutPageProps) {
  const resolvedSearchParams = (await searchParams) ?? {}
  const scopeParam = resolvedSearchParams.scope
  const scopeValue = Array.isArray(scopeParam) ? scopeParam[0] : scopeParam
  const projectScope =
    typeof scopeValue === 'string' && scopeValue.trim() ? scopeValue.trim() : 'summitflow'

  return (
    <NotesProvider apiPrefix="/api" projectScope={projectScope}>
      <div className="bg-grid flex min-h-dvh flex-col px-4 py-4 sm:px-6 sm:py-6">
        <div className="card min-h-0 flex-1 overflow-hidden rounded-[2rem]">
          <NotesPanel />
        </div>
      </div>
    </NotesProvider>
  )
}
