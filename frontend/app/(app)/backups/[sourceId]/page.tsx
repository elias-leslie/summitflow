import { SourceBackupsClient } from './SourceBackupsClient'

export default async function SourceBackupsPage({
  params,
}: {
  params: Promise<{ sourceId: string }>
}) {
  const { sourceId } = await params
  return <SourceBackupsClient sourceId={sourceId} />
}
