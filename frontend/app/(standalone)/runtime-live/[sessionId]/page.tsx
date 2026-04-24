import { LiveSessionWorkspace } from '@/components/runtime/LiveSessionWorkspace'

export default async function RuntimeLiveSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>
}) {
  const { sessionId } = await params
  return <LiveSessionWorkspace sessionId={sessionId} />
}
