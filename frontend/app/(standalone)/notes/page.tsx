import { NotesWorkspace } from '@summitflow/notes-ui'

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

  return <NotesWorkspace apiPrefix="/api" projectScope={projectScope} />
}
