import { Suspense } from 'react'
import { JohnnyChatClient } from './JohnnyChatClient'

export const metadata = {
  title: 'Chat with Johnny — SummitFlow',
}

function ChatLoading() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-600">
      <div className="w-6 h-6 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
      <span className="text-xs font-mono">Connecting to Johnny…</span>
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense fallback={<ChatLoading />}>
      <JohnnyChatClient />
    </Suspense>
  )
}
